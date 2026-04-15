<script lang="ts">
	import { v4 as uuidv4 } from 'uuid';
	import { getContext, onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { toast } from 'svelte-sonner';

	import { chatCompleted } from '$lib/apis';
	import { createNewChat, getChatById, getChatList, updateChatById } from '$lib/apis/chats';
	import { getNoteById } from '$lib/apis/notes';
	import { generateOpenAIChatCompletion } from '$lib/apis/openai';
	import ContentRenderer from '$lib/components/chat/Messages/ContentRenderer.svelte';
	import ArrowLeft from '$lib/components/icons/ArrowLeft.svelte';
	import ChatPlus from '$lib/components/icons/ChatPlus.svelte';
	import Download from '$lib/components/icons/Download.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import {
		chats,
		config,
		currentChatPage,
		models,
		settings,
		showSidebar,
		socket,
		user
	} from '$lib/stores';
	import { createMessagesList, processDetails, removeAllDetails } from '$lib/utils';

	type DraftNoteAttachment = {
		id: string;
		title: string;
		updated_at?: number;
		type: 'note';
		name: string;
		description: string;
		status: 'processed';
	};

	type FieldBossResultBootstrap = {
		prompt: string;
		files: DraftNoteAttachment[];
		skillId: string;
		skillName: string;
		modelId: string;
		codeInterpreterEnabled: boolean;
	};

	type HistoryMessage = {
		id: string;
		parentId: string | null;
		childrenIds: string[];
		role: 'user' | 'assistant';
		content: string;
		models?: string[];
		model?: string;
		modelName?: string;
		modelIdx?: number;
		done?: boolean;
		timestamp: number;
		usage?: unknown;
		sources?: unknown[];
		error?: { content: string };
	};

	const i18n = getContext('i18n');
	const FIELD_BOSS_RESULT_BOOTSTRAP_KEY = 'field-boss-result-bootstrap';
	const FIELD_BOSS_RESULT_SIDEBAR_STATE_KEY = 'field-boss-result-sidebar-state';
	const FIELD_BOSS_LATEST_ESTIMATE_CHAT_ID_KEY = 'field-boss-latest-estimate-chat-id';
	const FIELD_BOSS_NOTE_ESTIMATE_CHAT_IDS_KEY = 'field-boss-note-estimate-chat-ids';

	type FieldBossEstimateSnapshot = {
		source: 'fieldboss-estimate';
		noteId: string;
		noteTitle: string;
		noteContentFingerprint: string;
		modelId: string;
		skillId: string;
		skillName: string;
		prompt: string;
		rawContent: string;
		resultContent: string;
		structuredEstimate?: StructuredEstimateSnapshot;
		createdAt: number;
	};

	type StructuredEstimateExcludedItem = {
		item: string;
		reason: string;
	};

	type StructuredEstimateLineItem = {
		id: string;
		item: string;
		quantity: string;
		originalMaterialPerUnit: string;
		originalMaterialTotal: string;
		originalLaborTotal: string;
		originalTaskTotal: string;
		taskInput: string;
		taskTouched: boolean;
	};

	type StructuredEstimateComputedTotals = {
		totalMaterials: string;
		totalLabor: string;
		subtotal: string;
		contingency: string;
		totalCost: string;
		isValid: boolean;
	};

	type StructuredEstimateSnapshot = {
		excludedItems: StructuredEstimateExcludedItem[];
		lineItems: StructuredEstimateLineItem[];
		contingencyPercentInput: string;
	};

	type CurrencyParseResult = {
		state: 'valid' | 'blank' | 'invalid';
		value: number | null;
	};

	type EvaluatedLineItem = {
		id: string;
		item: string;
		quantity: string;
		materialPerUnitDisplay: string;
		materialTotalDisplay: string;
		laborDisplay: string;
		taskInput: string;
		taskDisplayValue: string;
		taskError: string;
		taskValue: number | null;
		isModified: boolean;
		isInvalid: boolean;
	};

	type EvaluatedEstimate = {
		excludedItems: StructuredEstimateExcludedItem[];
		lineItems: EvaluatedLineItem[];
		totals: StructuredEstimateComputedTotals;
		contingencyPercentInput: string;
		contingencyPercentError: string;
		contingencyRate: number;
		hasInvalidInputs: boolean;
	};

	let loaded = false;
	let generating = true;
	let errorMessage = '';
	let resultContent = '';
	let savedChatId: string | null = null;
	let bootstrap: FieldBossResultBootstrap | null = null;
	let restoredEstimate: FieldBossEstimateSnapshot | null = null;
	let previousSidebarState: boolean | null = null;
	let sourceNoteContentFingerprint = '';
	let structuredEstimate: StructuredEstimateSnapshot | null = null;
	let estimateSaveTimeout: ReturnType<typeof setTimeout> | null = null;
	let exportPdfNode: HTMLDivElement | null = null;
	let exportingPdf = false;
	let activeTaskTotalInputs: Record<string, string> = {};

	const responseMessageId = uuidv4();
	const history = {
		messages: {} as Record<string, HistoryMessage>,
		currentId: responseMessageId
	};

	$: activeModelId = bootstrap?.modelId ?? restoredEstimate?.modelId ?? '';
	$: selectedModel = $models.find((item) => item.id === activeModelId) ?? null;
	$: evaluatedEstimate = structuredEstimate
		? evaluateStructuredEstimate(structuredEstimate, activeTaskTotalInputs)
		: null;
	$: estimateCreatedAt = restoredEstimate?.createdAt ?? null;
	$: exportTimestampDisplay = formatEstimateTimestamp(estimateCreatedAt);
	$: rendererHistory =
		resultContent || errorMessage
			? {
					messages: {
						[responseMessageId]: {
							id: responseMessageId,
							parentId: null,
							childrenIds: [],
							role: 'assistant',
							content: errorMessage || resultContent,
							model: activeModelId,
							done: true,
							timestamp: Math.floor(Date.now() / 1000)
						}
					},
					currentId: responseMessageId
				}
			: { messages: {}, currentId: null };

	const stripTaggedBlocks = (content: string) =>
		content
			.replace(/<code_interpreter\b[^>]*>[\s\S]*?<\/code_interpreter>/gi, '')
			.replace(/<calculate-estimate\b[^>]*>[\s\S]*?<\/calculate-estimate>/gi, '')
			.replace(/<\$[^>]+>/g, '')
			.replace(/```[\s\S]*?```/g, '')
			.trim();

	const fingerprintNoteContent = (content: string) => content.replace(/\r\n/g, '\n').trim();

	const getDisplayContent = (content: string) => {
		const processed = processDetails(content);
		const withoutDetails = removeAllDetails(processed);
		return stripTaggedBlocks(withoutDetails);
	};

	const ESTIMATE_TABLE_FORMAT_INSTRUCTION = `
Return the estimate in markdown using exactly these sections when data is available:

## Excluded Items
| Item | Reason |
| --- | --- |

## Line Items
| Item | Quantity |  Material/Unit | Material Total | Labor Total | Task Total |
| --- | --- | --- | --- | --- | --- |

## Totals
| Metric | Amount |
| --- | --- |

Use currency formatting like $1,234.56. Use — for missing values. Do not replace these sections with prose-only bullets.
`.trim();

	type ParsedExcludedItem = {
		item: string;
		reason: string;
	};

	type ParsedLineItem = {
		item: string;
		quantity: string;
		materialPerUnit: string;
		materialTotal: string;
		laborTotal: string;
		taskTotal: string;
	};

	type ParsedTotal = {
		metric: string;
		amount: string;
	};

	const escapeMarkdownCell = (value: string) =>
		(value || '—')
			.replace(/\|/g, '\\|')
			.replace(/\n/g, ' ')
			.trim() || '—';

	const buildMarkdownTable = (headers: string[], rows: string[][]) => {
		const headerLine = `| ${headers.map(escapeMarkdownCell).join(' | ')} |`;
		const dividerLine = `| ${headers.map(() => '---').join(' | ')} |`;
		const rowLines = rows.map(
			(row) => `| ${row.map((cell) => escapeMarkdownCell(cell)).join(' | ')} |`
		);

		return [headerLine, dividerLine, ...rowLines].join('\n');
	};

	const hasMarkdownTable = (content: string) =>
		/\|[^\n]+\|\n\|\s*[-:| ]+\|/m.test(content) &&
		/(Excluded Items|Line Items|Totals)/i.test(content);

	const parseExcludedItem = (line: string): ParsedExcludedItem | null => {
		const match = line.match(/^[•*◦-]\s*(.+?)\s*:\s*(.+)$/);
		if (!match) return null;

		return {
			item: match[1].trim(),
			reason: match[2].trim()
		};
	};

	const parseQuantityLine = (line: string) => {
		const match = line.match(/^[•*◦-]\s*(.+?)\s*:\s*(.+?)(?:\s*\((.+)\))?$/);
		if (!match) return null;

		return {
			item: match[1].trim(),
			quantity: match[2].trim() || '—'
		};
	};

	const parseMaterialLine = (line: string) => {
		const match = line.match(
			/^[•*◦-]\s*Material\s*:\s*(.+?)(?:\s*\(Total:\s*(.+?)\))?$/i
		);
		if (!match) return null;

		return {
			perUnit: match[1].trim(),
			total: match[2]?.trim() || '—'
		};
	};

	const parseLabeledAmountLine = (line: string, label: string) => {
		const regex = new RegExp(`^[•*◦-]?\\s*${label}\\s*:\\s*(.+?)(?:\\s+total)?$`, 'i');
		const match = line.match(regex);
		return match?.[1]?.trim() || null;
	};

	const normalizeMetricName = (metric: string) => {
		const normalized = metric.replace(/^Totals?\s*:\s*/i, '').trim();

		if (/^cost of contingency/i.test(normalized)) return 'Contingency';
		if (/^total cost$/i.test(normalized)) return 'Total Cost';
		if (/^total materials?/i.test(normalized)) return 'Total Materials';
		if (/^total labor/i.test(normalized)) return 'Total Labor';
		if (/^subtotal/i.test(normalized)) return 'Subtotal';

		return normalized;
	};

	const normalizeEstimateToTables = (content: string) => {
		const cleaned = content.trim();
		if (!cleaned) return cleaned;
		if (hasMarkdownTable(cleaned)) return cleaned;

		const excludedItems: ParsedExcludedItem[] = [];
		const lineItems: ParsedLineItem[] = [];
		const totals: ParsedTotal[] = [];
		let currentSection: 'excluded' | 'lineItems' | 'totals' | null = null;
		let currentLineItem: ParsedLineItem | null = null;

		for (const rawLine of cleaned.split('\n')) {
			const line = rawLine.trim();
			if (!line) continue;

			if (/^excluded items\s*:?\s*$/i.test(line)) {
				currentSection = 'excluded';
				currentLineItem = null;
				continue;
			}

			if (/^(estimate summary|line items)\s*:?\s*$/i.test(line)) {
				currentSection = /line items/i.test(line) ? 'lineItems' : null;
				currentLineItem = null;
				continue;
			}

			if (/^totals?\s*:?\s*$/i.test(line)) {
				currentSection = 'totals';
				currentLineItem = null;
				continue;
			}

			if (/^totals?\s*:\s*/i.test(line)) {
				currentSection = 'totals';
				currentLineItem = null;

				const inlineTotal = line.replace(/^totals?\s*:\s*/i, '').trim();
				if (inlineTotal) {
					const inlineMatch = inlineTotal.match(/^(.+?)\s*:\s*(.+)$/);
					if (inlineMatch) {
						totals.push({
							metric: normalizeMetricName(inlineMatch[1]),
							amount: inlineMatch[2].trim()
						});
					}
				}
				continue;
			}

			if (currentSection === 'excluded') {
				const excludedItem = parseExcludedItem(line);
				if (excludedItem) {
					excludedItems.push(excludedItem);
				}
				continue;
			}

			if (currentSection === 'lineItems') {
				const quantityLine = parseQuantityLine(line);
				if (quantityLine && !/^(material|labor|task total)$/i.test(quantityLine.item)) {
					currentLineItem = {
						item: quantityLine.item,
						quantity: quantityLine.quantity,
						materialPerUnit: '—',
						materialTotal: '—',
						laborTotal: '—',
						taskTotal: '—'
					};
					lineItems.push(currentLineItem);
					continue;
				}

				if (!currentLineItem) continue;

				const material = parseMaterialLine(line);
				if (material) {
					currentLineItem.materialPerUnit = material.perUnit;
					currentLineItem.materialTotal = material.total;
					continue;
				}

				const labor = parseLabeledAmountLine(line, 'Labor');
				if (labor) {
					currentLineItem.laborTotal = labor;
					continue;
				}

				const taskTotal = parseLabeledAmountLine(line, 'Task Total');
				if (taskTotal) {
					currentLineItem.taskTotal = taskTotal;
				}
				continue;
			}

			const totalMatch = line.match(/^(.+?)\s*:\s*(.+)$/);
			if (currentSection === 'totals' && totalMatch) {
				totals.push({
					metric: normalizeMetricName(totalMatch[1]),
					amount: totalMatch[2].trim()
				});
			}
		}

		if (lineItems.length === 0 && totals.length === 0 && excludedItems.length === 0) {
			return cleaned;
		}

		const sections: string[] = [];

		if (excludedItems.length > 0) {
			sections.push(
				'## Excluded Items',
				buildMarkdownTable(
					['Item', 'Reason'],
					excludedItems.map((item) => [item.item, item.reason])
				)
			);
		}

		if (lineItems.length > 0) {
			sections.push(
				'## Line Items',
				buildMarkdownTable(
					[
						'Item',
						'Quantity',
						'Material/Unit',
						'Material Total',
						'Labor Total',
						'Task Total'
					],
					lineItems.map((item) => [
						item.item,
						item.quantity,
						item.materialPerUnit,
						item.materialTotal,
						item.laborTotal,
						item.taskTotal
					])
				)
			);
		}

		if (totals.length > 0) {
			sections.push(
				'## Totals',
				buildMarkdownTable(
					['Metric', 'Amount'],
					totals.map((item) => [item.metric, item.amount])
				)
			);
		}

		return sections.join('\n\n').trim() || cleaned;
	};

	const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

	const getMarkdownTableRows = (content: string, heading: string) => {
		const sectionMatch = content.match(
			new RegExp(`##\\s*${escapeRegExp(heading)}\\s*\\n([\\s\\S]*?)(?=\\n##\\s|$)`, 'i')
		);
		if (!sectionMatch) return [] as string[][];

		const tableLines = sectionMatch[1]
			.split('\n')
			.map((line) => line.trim())
			.filter((line) => line.startsWith('|'));

		if (tableLines.length < 2) return [] as string[][];

		return tableLines
			.slice(2)
			.map((line) =>
				line
					.slice(1, -1)
					.split('|')
					.map((cell) => cell.replace(/\\\|/g, '|').trim())
			)
			.filter((row) => row.some((cell) => cell !== ''));
	};

	const formatCurrency = (value: number) =>
		new Intl.NumberFormat('en-US', {
			style: 'currency',
			currency: 'USD',
			minimumFractionDigits: 2,
			maximumFractionDigits: 2
		}).format(value);

	const roundCurrency = (value: number) => Math.round(value * 100) / 100;

	const parseCurrencyInput = (value: string): CurrencyParseResult => {
		const trimmed = value.trim();
		if (!trimmed || trimmed === '—') {
			return { state: 'blank', value: null };
		}

		const normalized = trimmed.replace(/\$/g, '').replace(/,/g, '').replace(/\s+/g, '');
		if (!normalized) {
			return { state: 'blank', value: null };
		}

		if (!/^-?(?:\d+(?:\.\d{0,2})?|\d+\.)$/.test(normalized)) {
			return { state: 'invalid', value: null };
		}

		const parsed = Number.parseFloat(normalized);
		if (!Number.isFinite(parsed)) {
			return { state: 'invalid', value: null };
		}

		return { state: 'valid', value: parsed };
	};

	const parsePercentInput = (value: string): CurrencyParseResult => {
		const trimmed = value.trim();
		if (!trimmed) {
			return { state: 'blank', value: null };
		}

		const normalized = trimmed.replace(/%/g, '').replace(/\s+/g, '');
		if (!/^\d+(?:\.\d{0,2})?$/.test(normalized)) {
			return { state: 'invalid', value: null };
		}

		const parsed = Number.parseFloat(normalized);
		if (!Number.isFinite(parsed)) {
			return { state: 'invalid', value: null };
		}

		return { state: 'valid', value: parsed };
	};

	const normalizePercentInputForDisplay = (value: string) => {
		const trimmed = value.trim().replace(/%/g, '');
		if (!trimmed) return '';
		if (/^0$/.test(trimmed)) return '0';
		if (/^0+\d+$/.test(trimmed)) return `${Number.parseInt(trimmed, 10)}`;
		return trimmed;
	};

	const normalizeCurrencyInputForEditing = (value: string) => {
		const normalized = value.replace(/\$/g, '').replace(/,/g, '').replace(/^\s+/, '');
		return normalized ? `$${normalized}` : '$';
	};

	const getEditingCurrencyDisplayValue = (value: string) => {
		const parsed = parseCurrencyInput(value);
		if (parsed.state !== 'valid') {
			return normalizeCurrencyInputForEditing(value);
		}

		const normalized = value
			.trim()
			.replace(/\$/g, '')
			.replace(/,/g, '')
			.replace(/\s+/g, '')
			.replace(/(\.\d*?[1-9])0+$/u, '$1')
			.replace(/\.0+$/u, '')
			.replace(/\.$/u, '');

		return normalized ? `$${normalized}` : '$';
	};

	const formatCurrencyInputOnBlur = (value: string) => {
		const parsed = parseCurrencyInput(value);
		if (parsed.state !== 'valid' || parsed.value === null) {
			return normalizeCurrencyInputForEditing(value);
		}

		return formatCurrency(roundCurrency(parsed.value));
	};

	const getErrorMessage = (error: unknown, fallback: string) => {
		if (typeof error === 'string') {
			return error;
		}

		if (error instanceof Error) {
			return error.message || fallback;
		}

		if (error && typeof error === 'object') {
			const detail =
				'detail' in error
					? (error as { detail?: unknown }).detail
					: 'message' in error
						? (error as { message?: unknown }).message
						: null;

			if (typeof detail === 'string') {
				return detail;
			}

			if (Array.isArray(detail)) {
				const joined = detail
					.map((item) => {
						if (typeof item === 'string') return item;
						if (item && typeof item === 'object' && 'msg' in item) {
							return `${(item as { msg?: unknown }).msg ?? ''}`.trim();
						}
						return '';
					})
					.filter(Boolean)
					.join('; ');

				if (joined) return joined;
			}
		}

		return fallback;
	};

	const formatEstimateTimestamp = (timestamp: number | null) => {
		if (!timestamp) return '';

		try {
			return new Intl.DateTimeFormat(undefined, {
				dateStyle: 'medium',
				timeStyle: 'short'
			}).format(new Date(timestamp));
		} catch {
			return new Date(timestamp).toLocaleString();
		}
	};

	const sanitizeFileNamePart = (value: string) =>
		value
			.trim()
			.replace(/[\\/:*?"<>|]+/g, '-')
			.replace(/\s+/g, '-')
			.replace(/-+/g, '-')
			.replace(/^-|-$/g, '');

	const getExportFileName = () => {
		const titlePart = sanitizeFileNamePart(restoredEstimate?.noteTitle ?? '');
		const idPart = sanitizeFileNamePart(savedChatId ?? 'estimate');
		return `fieldboss-estimate-${titlePart || idPart}.pdf`;
	};

	const rehydrateStructuredEstimate = (
		estimate:
			| (Partial<StructuredEstimateSnapshot> & {
					lineItems?: Partial<StructuredEstimateLineItem>[];
					excludedItems?: Partial<StructuredEstimateExcludedItem>[];
			  })
			| null
			| undefined
	): StructuredEstimateSnapshot | null => {
		if (!estimate) return null;

		return {
			excludedItems: (estimate.excludedItems ?? []).map((item) => ({
				item: item.item ?? '',
				reason: item.reason ?? ''
			})),
			lineItems: (estimate.lineItems ?? []).map((lineItem, index) => ({
				id: lineItem.id ?? `line-item-${index}`,
				item: lineItem.item ?? '',
				quantity: lineItem.quantity ?? '',
				originalMaterialPerUnit: lineItem.originalMaterialPerUnit ?? '',
				originalMaterialTotal: lineItem.originalMaterialTotal ?? '',
				originalLaborTotal: lineItem.originalLaborTotal ?? '',
				originalTaskTotal: lineItem.originalTaskTotal ?? '',
				taskInput: lineItem.taskInput ?? lineItem.originalTaskTotal ?? '',
				taskTouched: lineItem.taskTouched ?? false
			})),
			contingencyPercentInput: normalizePercentInputForDisplay(
				estimate.contingencyPercentInput ?? '10'
			)
		};
	};

	const buildStructuredEstimate = (content: string): StructuredEstimateSnapshot | null => {
		const normalizedContent = normalizeEstimateToTables(content);
		const excludedRows = getMarkdownTableRows(normalizedContent, 'Excluded Items');
		const lineItemRows = getMarkdownTableRows(normalizedContent, 'Line Items');

		if (excludedRows.length === 0 && lineItemRows.length === 0) {
			return null;
		}

		const excludedItems = excludedRows.map((row) => ({
			item: row[0] ?? '',
			reason: row[1] ?? ''
		}));

		const lineItems = lineItemRows.map((row, index) => ({
			id: `line-item-${index}`,
			item: row[0] ?? '',
			quantity: row[1] ?? '',
			originalMaterialPerUnit: row[2] ?? '',
			originalMaterialTotal: row[3] ?? '',
			originalLaborTotal: row[4] ?? '',
			originalTaskTotal: row[5] ?? '',
			taskInput: row[5] ?? '',
			taskTouched: false
		}));

		return rehydrateStructuredEstimate({
			excludedItems,
			lineItems,
			contingencyPercentInput: '10'
		});
	};

	const getFieldError = (value: string, touched: boolean) => {
		if (!touched) return '';

		const parsed = parseCurrencyInput(value);
		if (parsed.state === 'blank') return $i18n.t('Enter a number');
		if (parsed.state === 'invalid') return $i18n.t('Enter a valid amount');
		return '';
	};

	const formatMaterialPerUnitDisplay = (value: string) =>
		value
			.trim()
			.replace(/\s*\/unit\s*$/i, '')
			.trim();

	const isLineItemModified = (lineItem: StructuredEstimateLineItem) => lineItem.taskTouched;

	const evaluateStructuredEstimate = (
		estimate: StructuredEstimateSnapshot,
		taskInputOverrides: Record<string, string>
	): EvaluatedEstimate => {
		const lineItems = estimate.lineItems.map((lineItem) => {
			const isModified = isLineItemModified(lineItem);
			const taskParsed = parseCurrencyInput(lineItem.taskInput);
			const taskError = getFieldError(lineItem.taskInput, lineItem.taskTouched);
			const originalTaskParsed = parseCurrencyInput(lineItem.originalTaskTotal);
			const taskValue =
				taskParsed.state === 'valid'
					? taskParsed.value
					: !isModified && originalTaskParsed.state === 'valid'
						? originalTaskParsed.value
						: null;
			const isInvalid =
				!!taskError || (isModified && taskParsed.state !== 'valid') || (!isModified && taskValue === null);

			return {
				id: lineItem.id,
				item: lineItem.item,
				quantity: lineItem.quantity,
				materialPerUnitDisplay: isModified
					? ''
					: formatMaterialPerUnitDisplay(lineItem.originalMaterialPerUnit),
				materialTotalDisplay: isModified || isInvalid ? '' : lineItem.originalMaterialTotal,
				laborDisplay: isModified || isInvalid ? '' : lineItem.originalLaborTotal,
				taskInput: lineItem.taskInput,
				taskDisplayValue: taskInputOverrides[lineItem.id] ?? lineItem.taskInput,
				taskError,
				taskValue,
				isModified,
				isInvalid
			};
		});

		const hasInvalidInputs = lineItems.some((lineItem) => lineItem.isInvalid);
		const hasEditedRows = lineItems.some((lineItem) => lineItem.isModified);
		const contingencyPercentParsed = parsePercentInput(estimate.contingencyPercentInput);
		const contingencyPercentError =
			contingencyPercentParsed.state === 'blank'
				? $i18n.t('Enter a percentage')
				: contingencyPercentParsed.state === 'invalid'
					? $i18n.t('Enter a valid percentage')
					: '';
		const contingencyRate =
			contingencyPercentParsed.state === 'valid'
				? (contingencyPercentParsed.value ?? 0) / 100
				: null;

		if (hasInvalidInputs) {
			return {
				excludedItems: estimate.excludedItems,
				lineItems,
				contingencyPercentInput: estimate.contingencyPercentInput,
				contingencyPercentError,
				contingencyRate: contingencyRate ?? 0.1,
				hasInvalidInputs,
				totals: {
					totalMaterials: '',
					totalLabor: '',
					subtotal: '',
					contingency: '',
					totalCost: '',
					isValid: false
				}
			};
		}

		const totalMaterials = hasEditedRows
			? ''
			: formatCurrency(
					roundCurrency(
						lineItems.reduce((sum, _lineItem, index) => {
							const parsed = parseCurrencyInput(estimate.lineItems[index].originalMaterialTotal);
							return sum + (parsed.state === 'valid' ? (parsed.value ?? 0) : 0);
						}, 0)
					)
				);
		const totalLabor = hasEditedRows
			? ''
			: formatCurrency(
					roundCurrency(
						lineItems.reduce((sum, _lineItem, index) => {
							const parsed = parseCurrencyInput(estimate.lineItems[index].originalLaborTotal);
							return sum + (parsed.state === 'valid' ? (parsed.value ?? 0) : 0);
						}, 0)
					)
				);
		const subtotal = roundCurrency(
			lineItems.reduce((sum, lineItem) => sum + (lineItem.taskValue ?? 0), 0)
		);
		const contingency =
			contingencyRate === null ? null : roundCurrency(subtotal * contingencyRate);
		const totalCost = contingency === null ? null : roundCurrency(subtotal + contingency);

		return {
			excludedItems: estimate.excludedItems,
			lineItems,
			contingencyPercentInput: estimate.contingencyPercentInput,
			contingencyPercentError,
			contingencyRate: contingencyRate ?? 0.1,
			hasInvalidInputs,
			totals: {
				totalMaterials,
				totalLabor,
				subtotal: formatCurrency(subtotal),
				contingency: contingency === null ? '' : formatCurrency(contingency),
				totalCost: totalCost === null ? '' : formatCurrency(totalCost),
				isValid: contingency !== null && totalCost !== null
			}
		};
	};

	const serializeStructuredEstimate = (
		estimate: StructuredEstimateSnapshot | null
	): StructuredEstimateSnapshot | undefined =>
		estimate
			? {
					excludedItems: estimate.excludedItems,
					lineItems: estimate.lineItems,
					contingencyPercentInput: normalizePercentInputForDisplay(
						estimate.contingencyPercentInput
					)
				}
			: undefined;

	const restoreSidebarPreference = () => {
		if (previousSidebarState === null) return;
		showSidebar.set(previousSidebarState);
		localStorage.sidebar = `${previousSidebarState}`;
		sessionStorage.removeItem(FIELD_BOSS_RESULT_SIDEBAR_STATE_KEY);
		previousSidebarState = null;
	};

	const backToFieldBoss = async () => {
		if (estimateSaveTimeout) clearTimeout(estimateSaveTimeout);
		restoreSidebarPreference();
		await goto('/fieldboss');
	};

	const openSavedChat = async () => {
		if (!savedChatId) return;
		if (estimateSaveTimeout) clearTimeout(estimateSaveTimeout);
		restoreSidebarPreference();
		await goto(`/c/${savedChatId}`);
	};

	const exportEstimateAsPdf = async () => {
		if (!evaluatedEstimate || !exportPdfNode || !savedChatId || exportingPdf) return;

		exportingPdf = true;

		try {
			await tick();

			const [{ default: jsPDF }, { default: html2canvas }] = await Promise.all([
				import('jspdf'),
				import('html2canvas-pro')
			]);

			const canvas = await html2canvas(exportPdfNode, {
				useCORS: true,
				backgroundColor: '#ffffff',
				scale: 2,
				width: exportPdfNode.scrollWidth,
				windowWidth: exportPdfNode.scrollWidth,
				windowHeight: exportPdfNode.scrollHeight
			});

			const imgData = canvas.toDataURL('image/jpeg', 0.92);
			const pdf = new jsPDF('p', 'mm', 'a4');
			const pageWidthMM = 210;
			const pageHeightMM = 297;
			const imgWidthMM = pageWidthMM;
			const imgHeightMM = (canvas.height * imgWidthMM) / canvas.width;
			let heightLeftMM = imgHeightMM;
			let positionMM = 0;

			pdf.addImage(imgData, 'JPEG', 0, positionMM, imgWidthMM, imgHeightMM);
			heightLeftMM -= pageHeightMM;

			while (heightLeftMM > 0) {
				positionMM -= pageHeightMM;
				pdf.addPage();
				pdf.addImage(imgData, 'JPEG', 0, positionMM, imgWidthMM, imgHeightMM);
				heightLeftMM -= pageHeightMM;
			}

			pdf.save(getExportFileName());
		} catch (error) {
			console.error(error);
			toast.error(getErrorMessage(error, $i18n.t('Failed to export PDF.')));
		} finally {
			exportingPdf = false;
		}
	};

	const getEstimateSnapshot = (
		rawContent: string,
		normalizedContent: string,
		nextStructuredEstimate: StructuredEstimateSnapshot | null
	): FieldBossEstimateSnapshot | null => {
		const source = bootstrap ?? restoredEstimate;
		const noteId = bootstrap?.files?.[0]?.id ?? restoredEstimate?.noteId;
		const noteTitle = bootstrap?.files?.[0]?.title ?? restoredEstimate?.noteTitle ?? '';
		if (!source || !noteId) return null;

		return {
			source: 'fieldboss-estimate',
			noteId,
			noteTitle,
			noteContentFingerprint: sourceNoteContentFingerprint,
			modelId: source.modelId,
			skillId: source.skillId,
			skillName: source.skillName,
			prompt: source.prompt,
			rawContent,
			resultContent: normalizedContent,
			structuredEstimate: serializeStructuredEstimate(nextStructuredEstimate),
			createdAt: Date.now()
		};
	};

	const syncEstimateSnapshotMetadata = (chatId: string, noteId: string) => {
		localStorage.setItem(FIELD_BOSS_LATEST_ESTIMATE_CHAT_ID_KEY, chatId);
		const noteEstimateChatIds = JSON.parse(
			localStorage.getItem(FIELD_BOSS_NOTE_ESTIMATE_CHAT_IDS_KEY) ?? '{}'
		) as Record<string, string>;
		noteEstimateChatIds[noteId] = chatId;
		localStorage.setItem(
			FIELD_BOSS_NOTE_ESTIMATE_CHAT_IDS_KEY,
			JSON.stringify(noteEstimateChatIds)
		);
	};

	const refreshEstimateChats = async () => {
		currentChatPage.set(1);
		chats.set(await getChatList(localStorage.token, $currentChatPage));
	};

	const persistEstimateSnapshot = async (
		chatId: string,
		snapshot: FieldBossEstimateSnapshot,
		options?: { syncMetadata?: boolean; refreshChats?: boolean }
	) => {
		const updatedChat = await updateChatById(localStorage.token, chatId, {
			fieldBossEstimate: snapshot
		});

		savedChatId = updatedChat?.id ?? chatId;

		if (options?.syncMetadata) {
			syncEstimateSnapshotMetadata(chatId, snapshot.noteId);
		}

		if (options?.refreshChats) {
			await refreshEstimateChats();
		}
	};

	const persistCurrentEstimateSnapshot = async () => {
		if (!savedChatId) return;

		const snapshot = getEstimateSnapshot(
			restoredEstimate?.rawContent ?? history.messages[responseMessageId]?.content ?? '',
			resultContent,
			structuredEstimate
		);
		if (!snapshot) return;

		restoredEstimate = snapshot;
		await persistEstimateSnapshot(savedChatId, snapshot);
	};

	const scheduleEstimateSnapshotSave = () => {
		if (!savedChatId || !structuredEstimate) return;
		if (estimateSaveTimeout) {
			clearTimeout(estimateSaveTimeout);
		}

		estimateSaveTimeout = setTimeout(async () => {
			estimateSaveTimeout = null;
			await persistCurrentEstimateSnapshot().catch((error) => {
				console.error(error);
			});
		}, 300);
	};

	const restoreEstimateFromChat = async (chatIdToRestore: string) => {
		const storedChat = await getChatById(localStorage.token, chatIdToRestore).catch(() => null);
		const snapshot = storedChat?.chat?.fieldBossEstimate as FieldBossEstimateSnapshot | undefined;

		if (!snapshot?.resultContent || snapshot.source !== 'fieldboss-estimate') {
			await goto('/fieldboss');
			return;
		}

		restoredEstimate = snapshot;
		savedChatId = chatIdToRestore;
		sourceNoteContentFingerprint = snapshot.noteContentFingerprint ?? '';
		resultContent = snapshot.resultContent;
		structuredEstimate = rehydrateStructuredEstimate(
			snapshot.structuredEstimate ?? buildStructuredEstimate(snapshot.resultContent)
		);
		generating = false;
		errorMessage = '';
		loaded = true;
	};

	const getFeatures = () => ({
		image_generation: false,
		web_search: false,
		code_interpreter:
			bootstrap?.codeInterpreterEnabled &&
			($config?.features?.enable_code_interpreter ?? false) &&
			($user?.role === 'admin' || ($user?.permissions?.features?.code_interpreter ?? false))
	});

	const createSavedChat = async (userMessage: HistoryMessage, responseMessage: HistoryMessage) => {
		history.messages = {
			[userMessage.id]: userMessage,
			[responseMessage.id]: responseMessage
		};
		history.currentId = responseMessage.id;

		const chat = await createNewChat(
			localStorage.token,
			{
				id: uuidv4(),
				title: $i18n.t('New Chat'),
				models: [bootstrap.modelId],
				system: $settings?.system ?? undefined,
				params: { ...($settings?.params ?? {}) },
				history,
				messages: createMessagesList(history, history.currentId),
				tags: [],
				timestamp: Date.now()
			},
			null
		);

		savedChatId = chat.id;

		const completed = await chatCompleted(localStorage.token, {
			model: bootstrap.modelId,
			messages: createMessagesList(history, history.currentId).map((message) => ({
				id: message.id,
				role: message.role,
				content: message.content,
				timestamp: message.timestamp,
				...(message.usage ? { usage: message.usage } : {}),
				...(message.sources ? { sources: message.sources } : {})
			})),
			model_item: selectedModel,
			chat_id: chat.id,
			session_id: $socket?.id,
			id: responseMessage.id
		}).catch((error) => {
			console.error(error);
			return null;
		});

		if (completed?.messages) {
			for (const message of completed.messages) {
				if (message?.id && history.messages[message.id]) {
					history.messages[message.id] = {
						...history.messages[message.id],
						...message
					};
				}
			}
		}

		await updateChatById(localStorage.token, chat.id, {
			models: [bootstrap.modelId],
			history,
			messages: createMessagesList(history, history.currentId),
			params: { ...($settings?.params ?? {}) }
		});
	};

	const handleEditableLineItemInput = (lineItemId: string, value: string) => {
		if (!structuredEstimate) return;

		const nextTaskInput = normalizeCurrencyInputForEditing(value);
		activeTaskTotalInputs = {
			...activeTaskTotalInputs,
			[lineItemId]: nextTaskInput
		};

		structuredEstimate = {
			...structuredEstimate,
			lineItems: structuredEstimate.lineItems.map((lineItem) =>
				lineItem.id === lineItemId
					? {
							...lineItem,
							taskInput: nextTaskInput,
							taskTouched: true
						}
					: lineItem
			)
		};

		scheduleEstimateSnapshotSave();
	};

	const handleEditableLineItemFocus = (lineItemId: string) => {
		if (!structuredEstimate) return;

		const lineItem = structuredEstimate.lineItems.find((item) => item.id === lineItemId);
		if (!lineItem) return;

		activeTaskTotalInputs = {
			...activeTaskTotalInputs,
			[lineItemId]: getEditingCurrencyDisplayValue(lineItem.taskInput)
		};
	};

	const handleEditableLineItemBlur = (lineItemId: string) => {
		if (!structuredEstimate) return;

		const currentTaskInput =
			activeTaskTotalInputs[lineItemId] ??
			structuredEstimate.lineItems.find((item) => item.id === lineItemId)?.taskInput ??
			'';
		const nextTaskInput = formatCurrencyInputOnBlur(currentTaskInput);
		const remainingTaskInputs = { ...activeTaskTotalInputs };
		delete remainingTaskInputs[lineItemId];
		activeTaskTotalInputs = remainingTaskInputs;

		structuredEstimate = {
			...structuredEstimate,
			lineItems: structuredEstimate.lineItems.map((lineItem) =>
				lineItem.id === lineItemId
					? {
							...lineItem,
							taskInput: nextTaskInput,
							taskTouched: true
						}
					: lineItem
			)
		};

		scheduleEstimateSnapshotSave();
	};

	const handleContingencyPercentInput = (value: string) => {
		if (!structuredEstimate) return;

		structuredEstimate = {
			...structuredEstimate,
			contingencyPercentInput: normalizePercentInputForDisplay(value)
		};

		scheduleEstimateSnapshotSave();
	};

	const generateEstimate = async () => {
		if (!bootstrap) {
			await goto('/fieldboss');
			return;
		}

		const userMessageId = uuidv4();
		const skillMention = `<$${bootstrap.skillId}|${bootstrap.skillName}>`;
		const storedPrompt = `${skillMention}\n${bootstrap.prompt}`.trim();
		const userMessage: HistoryMessage = {
			id: userMessageId,
			parentId: null,
			childrenIds: [responseMessageId],
			role: 'user',
			content: storedPrompt,
			models: [bootstrap.modelId],
			timestamp: Math.floor(Date.now() / 1000)
		};
		const responseMessage: HistoryMessage = {
			id: responseMessageId,
			parentId: userMessageId,
			childrenIds: [],
			role: 'assistant',
			content: '',
			model: bootstrap.modelId,
			modelName: selectedModel?.name ?? bootstrap.modelId,
			modelIdx: 0,
			done: true,
			timestamp: Math.floor(Date.now() / 1000)
		};

		const requestMessages = [
			...(($settings?.system ?? '').trim()
				? [{ role: 'system', content: `${$settings.system}` }]
				: []),
			{
				role: 'user',
				content: `${bootstrap.prompt}\n\n${ESTIMATE_TABLE_FORMAT_INSTRUCTION}`.trim()
			}
		];

		const result = await generateOpenAIChatCompletion(localStorage.token, {
			stream: false,
			model: bootstrap.modelId,
			messages: requestMessages,
			params: {
				...($settings?.params ?? {})
			},
			files: bootstrap.files,
			skill_ids: [bootstrap.skillId],
			features: getFeatures(),
			model_item: selectedModel,
			session_id: $socket?.id
		});

		if (!result) {
			throw new Error($i18n.t('Failed to generate estimate.'));
		}

		const rawContent = result?.choices?.[0]?.message?.content ?? '';
		if (!rawContent.trim()) {
			throw new Error($i18n.t('The model returned an empty response.'));
		}

		responseMessage.content = rawContent;
		responseMessage.usage = result?.usage;
		responseMessage.sources = result?.sources;

		await createSavedChat(userMessage, responseMessage);

		const persistedContent = history.messages[responseMessage.id]?.content ?? rawContent;
		const normalizedContent = normalizeEstimateToTables(getDisplayContent(persistedContent));
		resultContent = normalizedContent;
		structuredEstimate = buildStructuredEstimate(normalizedContent);

		const snapshot = getEstimateSnapshot(rawContent, normalizedContent, structuredEstimate);
		if (snapshot && savedChatId) {
			restoredEstimate = snapshot;
			await persistEstimateSnapshot(savedChatId, snapshot, {
				syncMetadata: true,
				refreshChats: true
			});
		}
	};

	onMount(async () => {
		if (
			!(
				($config?.features?.enable_notes ?? false) &&
				($user?.role === 'admin' || ($user?.permissions?.features?.notes ?? true))
			)
		) {
			goto('/');
			return;
		}

		previousSidebarState = $showSidebar;
		sessionStorage.setItem(
			FIELD_BOSS_RESULT_SIDEBAR_STATE_KEY,
			JSON.stringify(previousSidebarState)
		);
		showSidebar.set(false);

		const restoreChatId = $page.url.searchParams.get('chatId');
		if (restoreChatId) {
			await restoreEstimateFromChat(restoreChatId);
			return;
		}

		const rawBootstrap = sessionStorage.getItem(FIELD_BOSS_RESULT_BOOTSTRAP_KEY);
		if (!rawBootstrap) {
			goto('/fieldboss');
			return;
		}

		try {
			bootstrap = JSON.parse(rawBootstrap) as FieldBossResultBootstrap;
		} catch {
			sessionStorage.removeItem(FIELD_BOSS_RESULT_BOOTSTRAP_KEY);
			goto('/fieldboss');
			return;
		}

		sessionStorage.removeItem(FIELD_BOSS_RESULT_BOOTSTRAP_KEY);

		if (!bootstrap?.files?.[0]?.id) {
			goto('/fieldboss');
			return;
		}

		const note = await getNoteById(localStorage.token, bootstrap.files[0].id).catch(() => null);
		if (!note) {
			goto('/fieldboss');
			return;
		}

		sourceNoteContentFingerprint = fingerprintNoteContent(note?.data?.content?.md ?? '');

		loaded = true;

		const storedSidebarState = sessionStorage.getItem(FIELD_BOSS_RESULT_SIDEBAR_STATE_KEY);
		if (storedSidebarState && previousSidebarState === null) {
			try {
				previousSidebarState = JSON.parse(storedSidebarState);
			} catch {
				sessionStorage.removeItem(FIELD_BOSS_RESULT_SIDEBAR_STATE_KEY);
			}
		}

		try {
			await tick();
			await generateEstimate();
		} catch (error) {
			console.error(error);
			errorMessage = getErrorMessage(error, $i18n.t('Failed to generate estimate.'));
			toast.error(errorMessage);
		} finally {
			generating = false;
		}
	});
</script>

<svelte:head>
	<title>{$i18n.t('Field Boss Result')}</title>
</svelte:head>

{#if loaded}
	<div
		class="relative flex h-screen max-h-[100dvh] w-full flex-col overflow-hidden bg-gray-50 transition-width duration-200 ease-in-out dark:bg-gray-950 {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''}"
		data-saved-chat-id={savedChatId ?? undefined}
	>
		<div class="h-full overflow-y-auto px-6 pb-8 pt-5 md:px-8 md:pb-10 md:pt-8">
			<div class="mx-auto max-w-4xl">
				<div
					class="sticky top-0 z-20 -mx-6 mb-5 bg-gray-50 px-6 pb-4 pt-[max(1.25rem,env(safe-area-inset-top))] dark:bg-gray-950 md:-mx-8 md:mb-6 md:px-8 md:pt-0"
				>
					<div class="flex flex-col gap-3 min-[31rem]:flex-row min-[31rem]:items-center min-[31rem]:justify-between">
						<button
							class="rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 px-4 py-3 shadow-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition self-start"
							on:click={backToFieldBoss}
						>
							<div class="flex items-center gap-3 text-sm font-medium text-gray-900 dark:text-gray-100">
								<ArrowLeft className="size-4" strokeWidth="2" />
								<span>{$i18n.t('Back to FieldBoss')}</span>
							</div>
						</button>

						<div class="flex flex-col gap-3 self-start min-[31rem]:flex-row min-[31rem]:items-center min-[31rem]:self-auto">
							<button
								class="rounded-2xl border border-gray-200 bg-white px-4 py-3 text-gray-900 shadow-lg transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-100 dark:hover:bg-gray-850 self-start min-[31rem]:self-auto"
								on:click={exportEstimateAsPdf}
								disabled={!evaluatedEstimate || !savedChatId || generating || exportingPdf}
							>
								<div class="flex items-center gap-3 text-sm font-medium">
									<Download className="size-4" strokeWidth="2" />
									<span>{exportingPdf ? $i18n.t('Exporting PDF...') : $i18n.t('Export PDF')}</span>
								</div>
							</button>

							<button
								class="rounded-2xl bg-gray-900 text-white dark:bg-white dark:text-gray-900 px-4 py-3 shadow-lg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 self-start min-[31rem]:self-auto"
								on:click={openSavedChat}
								disabled={!savedChatId}
							>
								<div class="flex items-center gap-3 text-sm font-medium">
									<ChatPlus className="size-4.5" />
									<span>{$i18n.t('Open Chat')}</span>
								</div>
							</button>
						</div>
					</div>
				</div>

				<div class="rounded-[2rem] border border-gray-200 dark:border-gray-800 bg-white/95 dark:bg-gray-900/95 shadow-2xl min-h-[16rem]">
					<div class="border-b border-gray-100 dark:border-gray-800 px-6 py-5 md:px-8">
						<div class="text-xs uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
							{$i18n.t('Field Boss Result')}
						</div>
						<div class="mt-2 text-2xl font-semibold text-gray-900 dark:text-gray-100">
							{$i18n.t('Cost Estimate')}
						</div>
					</div>

					<div class="px-6 py-8 md:px-8">
						{#if generating}
							<div class="flex min-h-[16rem] flex-col items-center justify-center gap-4 text-center">
								<Spinner className="size-8" />
								<div class="text-sm text-gray-600 dark:text-gray-300">
									{$i18n.t('Generating estimate...')}
								</div>
							</div>
						{:else if errorMessage}
							<div class="min-h-[16rem] space-y-4">
								<div class="text-lg font-medium text-red-600 dark:text-red-400">
									{$i18n.t('Unable to generate estimate')}
								</div>
								<div class="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
									{errorMessage}
								</div>
							</div>
						{:else if evaluatedEstimate}
							<div class="space-y-8">
								{#if evaluatedEstimate.excludedItems.length > 0}
									<div class="space-y-4">
										<div class="text-2xl font-medium text-gray-900 dark:text-gray-100">
											{$i18n.t('Excluded Items')}
										</div>
										<div class="overflow-x-auto">
											<table class="w-full min-w-[28rem] table-auto border-collapse text-left">
												<thead>
													<tr class="border-b border-gray-200 dark:border-gray-800 text-gray-500 dark:text-gray-400">
														<th class="px-4 py-3 text-sm font-semibold uppercase tracking-wide">
															{$i18n.t('Item')}
														</th>
														<th class="px-4 py-3 text-sm font-semibold uppercase tracking-wide">
															{$i18n.t('Reason')}
														</th>
													</tr>
												</thead>
												<tbody>
													{#each evaluatedEstimate.excludedItems as item}
														<tr class="border-b border-gray-100 dark:border-gray-850 align-top">
															<td class="px-4 py-3 text-base text-gray-900 dark:text-gray-100">
																{item.item}
															</td>
															<td class="px-4 py-3 text-base text-gray-700 dark:text-gray-300">
																{item.reason}
															</td>
														</tr>
													{/each}
												</tbody>
											</table>
										</div>
									</div>
								{/if}

								<div class="space-y-4">
									<div class="text-2xl font-medium text-gray-900 dark:text-gray-100">
										{$i18n.t('Line Items')}
									</div>
									<div class="overflow-x-auto">
										<table class="w-full min-w-[48rem] table-fixed border-collapse text-left md:min-w-0">
											<thead>
												<tr class="border-b border-gray-200 dark:border-gray-800 text-gray-500 dark:text-gray-400">
													<th class="w-[24%] px-3 py-3 text-sm font-semibold uppercase tracking-wide md:px-2.5">
														{$i18n.t('Item')}
													</th>
													<th class="w-[10%] px-3 py-3 text-sm font-semibold uppercase tracking-wide md:px-2.5">
														{$i18n.t('Quantity')}
													</th>
													<th class="w-[14%] px-3 py-3 text-sm font-semibold uppercase tracking-wide md:px-2.5">
														{$i18n.t('Material/Unit')}
													</th>
													<th class="w-[14%] px-3 py-3 text-sm font-semibold uppercase tracking-wide md:px-2.5">
														{$i18n.t('Material Total')}
													</th>
													<th class="w-[19%] px-3 py-3 text-sm font-semibold uppercase tracking-wide md:px-2.5">
														{$i18n.t('Labor Total')}
													</th>
													<th class="w-[19%] px-3 py-3 text-sm font-semibold uppercase tracking-wide md:px-2.5">
														{$i18n.t('Task Total')}
													</th>
												</tr>
											</thead>
											<tbody>
												{#each evaluatedEstimate.lineItems as lineItem}
													<tr class="border-b border-gray-100 dark:border-gray-850 align-top">
														<td class="px-3 py-4 text-base text-gray-900 dark:text-gray-100 md:px-2.5">
															<div class="max-w-[12rem] whitespace-normal md:max-w-none break-words">
																{lineItem.item}
															</div>
														</td>
														<td class="px-3 py-4 text-base text-gray-700 dark:text-gray-300 md:px-2.5">
															{lineItem.quantity}
														</td>
														<td class="px-3 py-4 text-base text-gray-700 dark:text-gray-300 md:px-2.5 break-words">
															{lineItem.materialPerUnitDisplay}
														</td>
														<td class="px-3 py-4 text-base text-gray-700 dark:text-gray-300 md:px-2.5">
															<div>{lineItem.materialTotalDisplay}</div>
														</td>
														<td class="px-3 py-4 text-base text-gray-700 dark:text-gray-300 md:px-2.5">
															{lineItem.laborDisplay}
														</td>
														<td class="px-3 py-4 md:px-2.5">
															<input
																class="w-full min-w-[7rem] rounded-xl border bg-white px-2.5 py-2 text-base text-gray-900 outline-none transition md:min-w-0 dark:bg-gray-950 dark:text-gray-100 {lineItem.taskError
																	? 'border-red-400 focus:border-red-500'
																	: 'border-gray-200 focus:border-gray-400 dark:border-gray-800 dark:focus:border-gray-600'}"
																value={lineItem.taskDisplayValue}
																on:focus={() => handleEditableLineItemFocus(lineItem.id)}
																on:input={(event) =>
																	handleEditableLineItemInput(
																		lineItem.id,
																		(event.currentTarget as HTMLInputElement).value
																	)}
																on:blur={() => handleEditableLineItemBlur(lineItem.id)}
															/>
															{#if lineItem.taskError}
																<div class="mt-1 text-xs text-red-500 dark:text-red-400">
																	{lineItem.taskError}
																</div>
															{/if}
														</td>
													</tr>
												{/each}
											</tbody>
										</table>
									</div>
								</div>

								<div class="space-y-4">
									<div class="text-2xl font-medium text-gray-900 dark:text-gray-100">
										{$i18n.t('Totals')}
									</div>
									<div class="overflow-x-auto">
										<table class="w-full min-w-[28rem] table-auto border-collapse text-left">
											<thead>
												<tr class="border-b border-gray-200 dark:border-gray-800 text-gray-500 dark:text-gray-400">
													<th class="px-4 py-3 text-sm font-semibold uppercase tracking-wide">
														{$i18n.t('Metric')}
													</th>
													<th class="px-4 py-3 text-sm font-semibold uppercase tracking-wide">
														{$i18n.t('Amount')}
													</th>
												</tr>
											</thead>
											<tbody>
												<tr class="border-b border-gray-100 dark:border-gray-850">
													<td class="px-4 py-3 text-base text-gray-900 dark:text-gray-100">
														{$i18n.t('Total Materials')}
													</td>
													<td class="px-4 py-3 text-base text-gray-700 dark:text-gray-300">
														{evaluatedEstimate.totals.totalMaterials}
													</td>
												</tr>
												<tr class="border-b border-gray-100 dark:border-gray-850">
													<td class="px-4 py-3 text-base text-gray-900 dark:text-gray-100">
														{$i18n.t('Total Labor')}
													</td>
													<td class="px-4 py-3 text-base text-gray-700 dark:text-gray-300">
														{evaluatedEstimate.totals.totalLabor}
													</td>
												</tr>
												<tr class="border-b border-gray-100 dark:border-gray-850">
													<td class="px-4 py-3 text-base text-gray-900 dark:text-gray-100">
														{$i18n.t('Subtotal')}
													</td>
													<td class="px-4 py-3 text-base text-gray-700 dark:text-gray-300">
														{evaluatedEstimate.totals.subtotal}
													</td>
												</tr>
												<tr class="border-b border-gray-100 dark:border-gray-850">
													<td class="px-4 py-3 text-base text-gray-900 dark:text-gray-100">
														{$i18n.t('Contingency')}
													</td>
													<td class="px-4 py-3 text-base text-gray-700 dark:text-gray-300">
														<div class="flex items-center justify-between gap-3">
															<span>{evaluatedEstimate.totals.contingency}</span>
															<div class="flex flex-col items-end gap-1">
																<div class="flex items-center gap-2">
																	<input
																		class="w-[4.5rem] rounded-xl border bg-white px-2.5 py-2 text-base text-gray-900 outline-none transition dark:bg-gray-950 dark:text-gray-100 {evaluatedEstimate.contingencyPercentError
																			? 'border-red-400 focus:border-red-500'
																			: 'border-gray-200 focus:border-gray-400 dark:border-gray-800 dark:focus:border-gray-600'}"
																		value={evaluatedEstimate.contingencyPercentInput}
																		on:focus={(event) =>
																			(event.currentTarget as HTMLInputElement).select()}
																		on:input={(event) =>
																			handleContingencyPercentInput(
																				(event.currentTarget as HTMLInputElement).value
																			)}
																	/>
																	<span class="text-base text-gray-500 dark:text-gray-400">%</span>
																</div>
																{#if evaluatedEstimate.contingencyPercentError}
																	<div class="text-xs text-red-500 dark:text-red-400">
																		{evaluatedEstimate.contingencyPercentError}
																	</div>
																{/if}
															</div>
														</div>
													</td>
												</tr>
												<tr>
													<td class="px-4 py-3 text-base font-semibold text-gray-900 dark:text-gray-100">
														{$i18n.t('Total Cost')}
													</td>
													<td class="px-4 py-3 text-base font-semibold text-gray-900 dark:text-gray-100">
														{evaluatedEstimate.totals.totalCost}
													</td>
												</tr>
											</tbody>
										</table>
									</div>
									{#if evaluatedEstimate.hasInvalidInputs || evaluatedEstimate.contingencyPercentError}
										<div class="text-sm text-red-500 dark:text-red-400">
											{evaluatedEstimate.hasInvalidInputs
												? $i18n.t('Fix invalid line-item amounts to recalculate totals.')
												: $i18n.t('Fix the contingency percentage to recalculate totals.')}
										</div>
									{/if}
								</div>
							</div>
						{:else if resultContent}
							<ContentRenderer
								id={responseMessageId}
								content={resultContent}
								history={rendererHistory}
								messageId={responseMessageId}
								selectedModels={activeModelId ? [activeModelId] : []}
								done={true}
								model={selectedModel}
								sources={[]}
								floatingButtons={false}
								editCodeBlock={false}
							/>
						{:else}
							<div class="min-h-[16rem] text-sm text-gray-700 dark:text-gray-300">
								{$i18n.t('No displayable result was returned.')}
							</div>
						{/if}
					</div>
				</div>
			</div>
		</div>
	</div>

	{#if evaluatedEstimate}
		<div class="pointer-events-none fixed -left-[10000px] top-0 opacity-0" aria-hidden="true">
			<div
				bind:this={exportPdfNode}
				class="w-[1024px] bg-white px-12 py-12 text-gray-900"
			>
				<div class="border-b border-gray-300 pb-6">
					<div class="text-xs uppercase tracking-[0.16em] text-gray-500">Field Boss Result</div>
					<div class="mt-3 text-[2rem] font-semibold leading-none">Cost Estimate</div>
					<div class="mt-6 grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
						<div>
							<div class="font-semibold text-gray-500">Estimate ID</div>
							<div class="mt-1 text-gray-900">{savedChatId ?? '—'}</div>
						</div>
						<div>
							<div class="font-semibold text-gray-500">Created</div>
							<div class="mt-1 text-gray-900">{exportTimestampDisplay || '—'}</div>
						</div>
						{#if restoredEstimate?.noteTitle}
							<div class="col-span-2">
								<div class="font-semibold text-gray-500">Note</div>
								<div class="mt-1 text-gray-900">{restoredEstimate.noteTitle}</div>
							</div>
						{/if}
					</div>
				</div>

				<div class="mt-8 space-y-8">
					{#if evaluatedEstimate.excludedItems.length > 0}
						<div>
							<div class="mb-3 text-xl font-semibold">Excluded Items</div>
							<table class="w-full border-collapse text-left text-sm">
								<thead>
									<tr class="bg-gray-100 text-gray-700">
										<th class="border border-gray-300 px-3 py-2 font-semibold">Item</th>
										<th class="border border-gray-300 px-3 py-2 font-semibold">Reason</th>
									</tr>
								</thead>
								<tbody>
									{#each evaluatedEstimate.excludedItems as item}
										<tr>
											<td class="border border-gray-300 px-3 py-2 align-top">{item.item}</td>
											<td class="border border-gray-300 px-3 py-2 align-top">{item.reason}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{/if}

					<div>
						<div class="mb-3 text-xl font-semibold">Line Items</div>
						<table class="w-full border-collapse text-left text-sm">
							<thead>
								<tr class="bg-gray-100 text-gray-700">
									<th class="border border-gray-300 px-3 py-2 font-semibold">Item</th>
									<th class="border border-gray-300 px-3 py-2 font-semibold">Quantity</th>
									<th class="border border-gray-300 px-3 py-2 font-semibold">Material/Unit</th>
									<th class="border border-gray-300 px-3 py-2 font-semibold">Material Total</th>
									<th class="border border-gray-300 px-3 py-2 font-semibold">Labor Total</th>
									<th class="border border-gray-300 px-3 py-2 font-semibold">Task Total</th>
								</tr>
							</thead>
							<tbody>
								{#each evaluatedEstimate.lineItems as lineItem}
									<tr>
										<td class="border border-gray-300 px-3 py-2 align-top">{lineItem.item}</td>
										<td class="border border-gray-300 px-3 py-2 align-top">{lineItem.quantity}</td>
										<td class="border border-gray-300 px-3 py-2 align-top">
											{lineItem.materialPerUnitDisplay || '—'}
										</td>
										<td class="border border-gray-300 px-3 py-2 align-top">
											{lineItem.materialTotalDisplay || '—'}
										</td>
										<td class="border border-gray-300 px-3 py-2 align-top">
											{lineItem.laborDisplay || '—'}
										</td>
										<td class="border border-gray-300 px-3 py-2 align-top">
											{lineItem.taskInput || '—'}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>

					<div>
						<div class="mb-3 text-xl font-semibold">Totals</div>
						<table class="w-full border-collapse text-left text-sm">
							<thead>
								<tr class="bg-gray-100 text-gray-700">
									<th class="border border-gray-300 px-3 py-2 font-semibold">Metric</th>
									<th class="border border-gray-300 px-3 py-2 font-semibold">Amount</th>
								</tr>
							</thead>
							<tbody>
								<tr>
									<td class="border border-gray-300 px-3 py-2">Total Materials</td>
									<td class="border border-gray-300 px-3 py-2">
										{evaluatedEstimate.totals.totalMaterials || '—'}
									</td>
								</tr>
								<tr>
									<td class="border border-gray-300 px-3 py-2">Total Labor</td>
									<td class="border border-gray-300 px-3 py-2">
										{evaluatedEstimate.totals.totalLabor || '—'}
									</td>
								</tr>
								<tr>
									<td class="border border-gray-300 px-3 py-2">Subtotal</td>
									<td class="border border-gray-300 px-3 py-2">
										{evaluatedEstimate.totals.subtotal || '—'}
									</td>
								</tr>
								<tr>
									<td class="border border-gray-300 px-3 py-2">Contingency</td>
									<td class="border border-gray-300 px-3 py-2">
										<div class="flex items-center justify-between gap-4">
											<span>{evaluatedEstimate.totals.contingency || '—'}</span>
											<span class="text-gray-600">
												{evaluatedEstimate.contingencyPercentInput || '—'}%
											</span>
										</div>
									</td>
								</tr>
								<tr>
									<td class="border border-gray-300 px-3 py-2 font-semibold">Total Cost</td>
									<td class="border border-gray-300 px-3 py-2 font-semibold">
										{evaluatedEstimate.totals.totalCost || '—'}
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
	{/if}
{/if}
