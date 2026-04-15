<script lang="ts">
	import { getContext, onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { marked } from 'marked';

	import dayjs from '$lib/dayjs';
	import { config, models, showSidebar, user } from '$lib/stores';
	import { transcribeAudio } from '$lib/apis/audio';
	import { getNoteById, updateNoteById } from '$lib/apis/notes';
	import { getSkills } from '$lib/apis/skills';
	import Mic from '$lib/components/icons/Mic.svelte';
	import NoteIcon from '$lib/components/icons/Note.svelte';
	import ArrowRight from '$lib/components/icons/ArrowRight.svelte';
	import ChatPlus from '$lib/components/icons/ChatPlus.svelte';
	import ClaraNotePicker from '$lib/components/clara/ClaraNotePicker.svelte';

	type RecorderStatus = 'idle' | 'recording' | 'transcribing' | 'saving' | 'success' | 'error';
	type SelectedNote = {
		id: string;
		title: string;
	};
	type SkillItem = {
		id: string;
		name?: string;
		is_active?: boolean;
	};
	type DraftNoteAttachment = {
		id: string;
		title: string;
		updated_at?: number;
		type: 'note';
		name: string;
		description: string;
		status: 'processed';
	};
	type ClaraResultBootstrap = {
		prompt: string;
		files: DraftNoteAttachment[];
		skillId: string;
		skillName: string;
		modelId: string;
		codeInterpreterEnabled: boolean;
	};

	const i18n = getContext('i18n');
	const CLARA_TARGET_NOTE_STORAGE_KEY = 'clara-target-note-id';
	const CLARA_RESULT_BOOTSTRAP_KEY = 'clara-result-bootstrap';
	const COST_CHAT_MODEL_ID = 'models/gemini-3.1-flash-lite-preview';
	const COST_ESTIMATE_SKILL_KEY = 'calculate-estimate';
	const COST_CHAT_CODE_INTERPRETER_ENABLED = false;
	const MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm; codecs=opus', 'audio/mp4'];

	let loaded = false;
	let showNotePicker = false;
	let selectedNote: SelectedNote | null = null;
	let status: RecorderStatus = 'idle';
	let statusMessage = '';

	let mediaRecorder: MediaRecorder | null = null;
	let stream: MediaStream | null = null;
	let audioChunks: Blob[] = [];

	const canRecord = () => status === 'idle' || status === 'success' || status === 'error';
	const canStartCostChat = () =>
		!!selectedNote && !['recording', 'transcribing', 'saving'].includes(status);
	const clearReplacedFeatureStorage = () => {
		const replacedFeaturePrefix = ['field', 'boss'].join('-');
		[
			'target-note-id',
			'result-bootstrap',
			'result-sidebar-state',
			'latest-estimate-chat-id',
			'note-estimate-chat-ids',
			'cost-chat-bootstrap'
		].forEach((suffix) => {
			const key = `${replacedFeaturePrefix}-${suffix}`;
			localStorage.removeItem(key);
			sessionStorage.removeItem(key);
		});
	};

	const describeNote = (updatedAt?: number) =>
		updatedAt ? dayjs(updatedAt / 1000000).fromNow() : $i18n.t('Clara');

	const appendTranscript = (existingContent: string, transcript: string) => {
		const trimmedExisting = existingContent.trim();
		const trimmedTranscript = transcript.trim();
		const heading = `## ${dayjs().format('YYYY-MM-DD HH:mm')}`;
		const block = `${heading}\n${trimmedTranscript}`;
		return trimmedExisting ? `${trimmedExisting}\n\n${block}` : block;
	};

	const stopStream = () => {
		if (stream) {
			stream.getTracks().forEach((track) => track.stop());
			stream = null;
		}
	};

	const resetRecorder = () => {
		mediaRecorder = null;
		audioChunks = [];
		stopStream();
	};

	const setSelectedNote = (note) => {
		selectedNote = {
			id: note.id,
			title: note.title || $i18n.t('Untitled')
		};
		localStorage.setItem(CLARA_TARGET_NOTE_STORAGE_KEY, note.id);
		status = 'idle';
		statusMessage = $i18n.t('Ready to record into {{title}}.', {
			title: selectedNote.title
		});
	};

	const loadSelectedNote = async () => {
		const noteId = localStorage.getItem(CLARA_TARGET_NOTE_STORAGE_KEY);
		if (!noteId) return;

		const note = await getNoteById(localStorage.token, noteId).catch(() => null);
		if (!note) {
			localStorage.removeItem(CLARA_TARGET_NOTE_STORAGE_KEY);
			return;
		}

		setSelectedNote(note);
	};

	const persistTranscript = async (transcript: string) => {
		if (!selectedNote) {
			status = 'error';
			statusMessage = $i18n.t('Select or create a note before recording.');
			return;
		}

		status = 'saving';
		statusMessage = $i18n.t('Saving to {{title}}...', { title: selectedNote.title });

		const note = await getNoteById(localStorage.token, selectedNote.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (!note) {
			localStorage.removeItem(CLARA_TARGET_NOTE_STORAGE_KEY);
			selectedNote = null;
			status = 'error';
			statusMessage = $i18n.t('The selected note is no longer available.');
			return;
		}

		const nextMd = appendTranscript(note.data?.content?.md ?? '', transcript);
		const nextHtml = await marked.parse(nextMd);

		const res = await updateNoteById(localStorage.token, note.id, {
			title: note.title,
			data: {
				...(note.data ?? {}),
				content: {
					...(note.data?.content ?? {}),
					json: null,
					md: nextMd,
					html: nextHtml
				}
			},
			meta: note.meta ?? {},
			access_grants: note.access_grants ?? []
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (!res) {
			status = 'error';
			statusMessage = $i18n.t('Unable to append transcript to the selected note.');
			return;
		}

		setSelectedNote(res);
		status = 'success';
		statusMessage = $i18n.t('Appended transcript to {{title}}.', { title: res.title });
	};

	const resolveCostEstimateSkill = async () => {
		const skills = (await getSkills(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return null;
		})) as SkillItem[] | null;

		if (!skills) return null;

		return (
			skills.find(
				(skill) =>
					skill?.is_active !== false &&
					[skill.id, skill.name]
						.filter(Boolean)
						.some((value) => value?.toLowerCase() === COST_ESTIMATE_SKILL_KEY)
			) ?? null
		);
	};

	const startCostChat = async () => {
		if (!selectedNote || !canStartCostChat()) return;

		const model = $models.find((item) => item.id === COST_CHAT_MODEL_ID);
		if (!model) {
			toast.error($i18n.t('The required model is not available.'));
			return;
		}

		if (model?.info?.meta?.capabilities?.file_upload === false) {
			toast.error($i18n.t('The required model does not support note attachments.'));
			return;
		}

		const note = await getNoteById(localStorage.token, selectedNote.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (!note) {
			localStorage.removeItem(CLARA_TARGET_NOTE_STORAGE_KEY);
			selectedNote = null;
			status = 'error';
			statusMessage = $i18n.t('The selected note is no longer available.');
			return;
		}

		const skill = await resolveCostEstimateSkill();
		if (!skill) {
			toast.error($i18n.t('The cost-estimate skill is not available.'));
			return;
		}

		const attachment: DraftNoteAttachment = {
			...note,
			type: 'note',
			name: note.title || $i18n.t('Untitled'),
			description: describeNote(note.updated_at),
			status: 'processed'
		};

		const bootstrap: ClaraResultBootstrap = {
			prompt: `${$i18n.t('Use the attached note to estimate project costs.')}`,
			files: [attachment],
			skillId: skill.id,
			skillName: skill.name || COST_ESTIMATE_SKILL_KEY,
			modelId: COST_CHAT_MODEL_ID,
			codeInterpreterEnabled: COST_CHAT_CODE_INTERPRETER_ENABLED
		};

		sessionStorage.setItem(CLARA_RESULT_BOOTSTRAP_KEY, JSON.stringify(bootstrap));

		await goto('/clara/result');
	};

	const handleAudioBlob = async (audioBlob: Blob) => {
		const ext = (audioBlob.type.split('/')[1] || 'webm').split(';')[0];
		const file = new File([audioBlob], `clara-${dayjs().format('YYYYMMDD-HHmmss')}.${ext}`, {
			type: audioBlob.type || 'audio/webm'
		});

		status = 'transcribing';
		statusMessage = $i18n.t('Transcribing audio...');

		const result = await transcribeAudio(localStorage.token, file).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (!result?.text?.trim()) {
			status = 'error';
			statusMessage = $i18n.t('Transcription failed.');
			return;
		}

		await persistTranscript(result.text);
	};

	const stopRecording = async () => {
		if (status !== 'recording' || !mediaRecorder) return;

		const recorder = mediaRecorder;
		const audioBlob = await new Promise<Blob | null>((resolve) => {
			recorder.onstop = () => {
				const mimeType = audioChunks[0]?.type || recorder.mimeType || 'audio/webm';
				resolve(audioChunks.length ? new Blob(audioChunks, { type: mimeType }) : null);
			};
			recorder.stop();
		});

		resetRecorder();

		if (!audioBlob) {
			status = 'error';
			statusMessage = $i18n.t('No audio was captured.');
			return;
		}

		await handleAudioBlob(audioBlob);
	};

	const startRecording = async () => {
		if (!selectedNote) {
			status = 'error';
			statusMessage = $i18n.t('Select or create a note before recording.');
			return;
		}

		try {
			stream = await navigator.mediaDevices.getUserMedia({
				audio: {
					echoCancellation: true,
					noiseSuppression: true,
					autoGainControl: true
				}
			});
		} catch (error) {
			console.error(error);
			status = 'error';
			statusMessage = $i18n.t('Error accessing media devices.');
			toast.error($i18n.t('Error accessing media devices.'));
			return;
		}

		audioChunks = [];
		const mimeType = MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
		mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
		mediaRecorder.ondataavailable = (event) => {
			if (event.data?.size) {
				audioChunks.push(event.data);
			}
		};

		mediaRecorder.start();
		status = 'recording';
		statusMessage = $i18n.t('Recording into {{title}}. Tap again to stop.', {
			title: selectedNote.title
		});
	};

	const toggleRecording = async () => {
		if (status === 'recording') {
			await stopRecording();
			return;
		}

		if (!canRecord()) return;
		await startRecording();
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

		clearReplacedFeatureStorage();

		await loadSelectedNote();

		if (!selectedNote) {
			statusMessage = $i18n.t('Select or create a note to start recording.');
		}

		loaded = true;
	});

	onDestroy(() => {
		if (mediaRecorder && mediaRecorder.state !== 'inactive') {
			mediaRecorder.stop();
		}
		resetRecorder();
	});
</script>

<svelte:head>
	<title>{$i18n.t('Clara')}</title>
</svelte:head>

<ClaraNotePicker
	bind:show={showNotePicker}
	on:select={(event) => setSelectedNote(event.detail)}
	on:create={(event) => setSelectedNote(event.detail)}
/>

{#if loaded}
	<div class="relative w-full h-screen max-h-[100dvh] overflow-hidden bg-gray-50 dark:bg-gray-950">
		<div class="absolute inset-0 flex items-center justify-center px-6">
			<div class="flex flex-col items-center gap-6 text-center">
				<button
					class="size-52 md:size-64 rounded-full border transition duration-200 flex items-center justify-center shadow-2xl disabled:cursor-not-allowed disabled:opacity-60
						{status === 'recording'
							? 'bg-red-600 border-red-500 text-white scale-105'
							: 'bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-800 text-gray-900 dark:text-gray-100 hover:scale-[1.02]'}"
					on:click={toggleRecording}
					disabled={!selectedNote || ['transcribing', 'saving'].includes(status)}
					aria-label={status === 'recording' ? $i18n.t('Stop Recording') : $i18n.t('Record')}
				>
					<div class="flex flex-col items-center gap-3">
						<Mic className="size-12 md:size-14" strokeWidth="2" />
						<div class="text-xl md:text-2xl font-medium">
							{#if status === 'recording'}
								{$i18n.t('Stop Recording')}
							{:else if ['transcribing', 'saving'].includes(status)}
								{$i18n.t('Processing...')}
							{:else}
								{$i18n.t('Record')}
							{/if}
						</div>
					</div>
				</button>

				<div class="min-h-[3rem] space-y-1">
					<div class="text-sm md:text-base text-gray-600 dark:text-gray-300">
						{statusMessage}
					</div>
					{#if selectedNote}
						<div class="text-xs md:text-sm text-gray-500 dark:text-gray-400">
							{$i18n.t('Target note')}: {selectedNote.title}
						</div>
					{:else}
						<button
							class="mt-3 rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 px-4 py-3 shadow-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
							on:click={() => {
								showNotePicker = true;
							}}
						>
							<div class="flex items-center gap-3 text-sm font-medium text-gray-900 dark:text-gray-100">
								<NoteIcon className="size-4.5" />
								<span>{$i18n.t('Select or Create Note')}</span>
							</div>
						</button>
					{/if}
				</div>
			</div>
		</div>

		<div
			class="absolute bottom-5 md:bottom-8 right-5 md:right-8 z-20 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between {$showSidebar
				? 'left-5 md:left-[calc(var(--sidebar-width)+5.75rem)]'
				: 'left-5 md:left-[5.75rem]'}"
		>
			<div class="flex flex-col gap-3 sm:flex-row sm:items-center">
				<button
					class="rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 px-4 py-3 shadow-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					on:click={() => {
						showNotePicker = true;
					}}
				>
					<div class="flex items-center gap-3 text-left">
						<NoteIcon className="size-4.5 shrink-0" />
						<div class="min-w-0 sm:min-w-[12rem] sm:max-w-[16rem]">
							<div class="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">
								{$i18n.t('Append To')}
							</div>
							<div class="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
								{selectedNote ? selectedNote.title : $i18n.t('Select or Create Note')}
							</div>
						</div>
					</div>
				</button>

				{#if selectedNote}
					<a
						class="inline-flex items-center gap-2 self-start rounded-xl px-3 py-2 text-sm font-medium text-gray-600 hover:bg-white/70 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-900/70 dark:hover:text-gray-100 transition sm:rounded-2xl sm:bg-gray-900 sm:text-white sm:px-4 sm:py-3 sm:shadow-lg sm:hover:opacity-90 sm:hover:bg-gray-900 dark:sm:bg-white dark:sm:text-gray-900"
						href={`/notes/${selectedNote.id}`}
					>
						<span>{$i18n.t('Open Note')}</span>
						<ArrowRight className="size-4" strokeWidth="2" />
					</a>
				{/if}
			</div>

			<button
				class="rounded-2xl bg-gray-900 text-white dark:bg-white dark:text-gray-900 px-4 py-3 shadow-lg transition disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 sm:ml-auto"
				on:click={startCostChat}
				disabled={!canStartCostChat()}
			>
				<div class="flex items-center gap-3 text-left">
					<ChatPlus className="size-4.5 shrink-0" />
					<div class="min-w-0 sm:min-w-[12rem] sm:max-w-[16rem]">
						<div class="text-xs uppercase tracking-[0.14em] text-white/70 dark:text-gray-500">
							{$i18n.t('Next Step')}
						</div>
						<div class="truncate text-sm font-medium">
							{$i18n.t('Start Cost Chat')}
						</div>
					</div>
				</div>
			</button>
		</div>
	</div>
{/if}
