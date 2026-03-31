<script lang="ts">
	import { getContext, onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { marked } from 'marked';

	import dayjs from '$lib/dayjs';
	import { config, showSidebar, user } from '$lib/stores';
	import { transcribeAudio } from '$lib/apis/audio';
	import { getNoteById, updateNoteById } from '$lib/apis/notes';
	import Mic from '$lib/components/icons/Mic.svelte';
	import NoteIcon from '$lib/components/icons/Note.svelte';
	import ArrowRight from '$lib/components/icons/ArrowRight.svelte';
	import SimpleModeNotePicker from '$lib/components/simple/SimpleModeNotePicker.svelte';

	type RecorderStatus = 'idle' | 'recording' | 'transcribing' | 'saving' | 'success' | 'error';
	type SelectedNote = {
		id: string;
		title: string;
	};

	const i18n = getContext('i18n');
	const STORAGE_KEY = 'simple-mode-target-note-id';
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
		localStorage.setItem(STORAGE_KEY, note.id);
		status = 'idle';
		statusMessage = $i18n.t('Ready to record into {{title}}.', {
			title: selectedNote.title
		});
	};

	const loadSelectedNote = async () => {
		const noteId = localStorage.getItem(STORAGE_KEY);
		if (!noteId) return;

		const note = await getNoteById(localStorage.token, noteId).catch(() => null);
		if (!note) {
			localStorage.removeItem(STORAGE_KEY);
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
			localStorage.removeItem(STORAGE_KEY);
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

	const handleAudioBlob = async (audioBlob: Blob) => {
		const ext = (audioBlob.type.split('/')[1] || 'webm').split(';')[0];
		const file = new File([audioBlob], `simple-mode-${dayjs().format('YYYYMMDD-HHmmss')}.${ext}`, {
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
	<title>{$i18n.t('Simple Mode')}</title>
</svelte:head>

<SimpleModeNotePicker
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
			class="absolute bottom-5 md:bottom-8 flex items-center gap-3 z-20 {$showSidebar
				? 'left-[calc(var(--sidebar-width)+5.75rem)]'
				: 'left-[5.75rem]'}"
		>
			<button
				class="rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 px-4 py-3 shadow-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
				on:click={() => {
					showNotePicker = true;
				}}
			>
				<div class="flex items-center gap-3 text-left">
					<NoteIcon className="size-4.5" />
					<div class="min-w-[12rem] max-w-[16rem]">
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
					class="rounded-2xl bg-gray-900 text-white dark:bg-white dark:text-gray-900 px-4 py-3 shadow-lg hover:opacity-90 transition"
					href={`/notes/${selectedNote.id}`}
				>
					<div class="flex items-center gap-2 text-sm font-medium">
						<span>{$i18n.t('Open Note')}</span>
						<ArrowRight className="size-4" strokeWidth="2" />
					</div>
				</a>
			{/if}
		</div>
	</div>
{/if}
