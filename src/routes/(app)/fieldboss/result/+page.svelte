<script lang="ts">
	import { v4 as uuidv4 } from 'uuid';
	import { getContext, onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { chatCompleted } from '$lib/apis';
	import { createNewChat, getChatList, updateChatById } from '$lib/apis/chats';
	import { getNoteById } from '$lib/apis/notes';
	import { generateOpenAIChatCompletion } from '$lib/apis/openai';
	import ContentRenderer from '$lib/components/chat/Messages/ContentRenderer.svelte';
	import ArrowLeft from '$lib/components/icons/ArrowLeft.svelte';
	import ChatPlus from '$lib/components/icons/ChatPlus.svelte';
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

	let loaded = false;
	let generating = true;
	let errorMessage = '';
	let resultContent = '';
	let savedChatId: string | null = null;
	let bootstrap: FieldBossResultBootstrap | null = null;
	let previousSidebarState: boolean | null = null;

	const responseMessageId = uuidv4();
	const history = {
		messages: {} as Record<string, HistoryMessage>,
		currentId: responseMessageId
	};

	$: selectedModel = $models.find((item) => item.id === bootstrap?.modelId) ?? null;
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
							model: bootstrap?.modelId ?? '',
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

	const getDisplayContent = (content: string) => {
		const processed = processDetails(content);
		const withoutDetails = removeAllDetails(processed);
		return stripTaggedBlocks(withoutDetails);
	};

	const restoreSidebarPreference = () => {
		if (previousSidebarState === null) return;
		showSidebar.set(previousSidebarState);
		localStorage.sidebar = `${previousSidebarState}`;
		sessionStorage.removeItem(FIELD_BOSS_RESULT_SIDEBAR_STATE_KEY);
		previousSidebarState = null;
	};

	const backToFieldBoss = async () => {
		restoreSidebarPreference();
		await goto('/fieldboss');
	};

	const openSavedChat = async () => {
		if (!savedChatId) return;
		restoreSidebarPreference();
		await goto(`/c/${savedChatId}`);
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

		currentChatPage.set(1);
		chats.set(await getChatList(localStorage.token, $currentChatPage));
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
			{ role: 'user', content: bootstrap.prompt }
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
		}).catch((error) => {
			console.error(error);
			return null;
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
		resultContent = getDisplayContent(persistedContent);
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

		previousSidebarState = $showSidebar;
		sessionStorage.setItem(
			FIELD_BOSS_RESULT_SIDEBAR_STATE_KEY,
			JSON.stringify(previousSidebarState)
		);
		showSidebar.set(false);

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
			errorMessage = error instanceof Error ? error.message : `${error}`;
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
		<div class="absolute left-5 right-5 top-5 md:left-8 md:right-8 md:top-8 z-20">
			<div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
				<button
					class="rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 px-4 py-3 shadow-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition self-start"
					on:click={backToFieldBoss}
				>
					<div class="flex items-center gap-3 text-sm font-medium text-gray-900 dark:text-gray-100">
						<ArrowLeft className="size-4" strokeWidth="2" />
						<span>{$i18n.t('Back to FieldBoss')}</span>
					</div>
				</button>

				<button
					class="rounded-2xl bg-gray-900 text-white dark:bg-white dark:text-gray-900 px-4 py-3 shadow-lg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 self-start sm:self-auto"
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

		<div class="h-full overflow-y-auto px-6 py-24 md:px-8">
			<div class="mx-auto max-w-4xl">
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
						{:else if resultContent}
							<ContentRenderer
								id={responseMessageId}
								content={resultContent}
								history={rendererHistory}
								messageId={responseMessageId}
								selectedModels={[bootstrap.modelId]}
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
{/if}
