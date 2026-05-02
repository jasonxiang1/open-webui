<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import dayjs from '$lib/dayjs';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Note from '$lib/components/icons/Note.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import { createNewNote, getNoteList } from '$lib/apis/notes';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	type NoteItem = {
		id: string;
		title: string;
		updated_at: number;
	};

	export let show = false;

	let loading = false;
	let creating = false;
	let noteList: NoteItem[] = [];
	let newNoteTitle = '';

	const getDefaultNoteTitle = () => dayjs().format('YYYY-MM-DD HH:mm');

	const close = () => {
		show = false;
		newNoteTitle = '';
	};

	const loadNotes = async () => {
		loading = true;
		const res = await getNoteList(localStorage.token).catch((error) => {
			toast.error(`${error}`);
			return [];
		});
		noteList = Array.isArray(res) ? res : [];
		loading = false;
	};

	const selectNote = (note) => {
		dispatch('select', note);
		close();
	};

	const createNote = async () => {
		if (creating) return;

		creating = true;
		const title = newNoteTitle.trim() || getDefaultNoteTitle();
		const note = await createNewNote(localStorage.token, {
			title,
			data: {
				content: {
					json: null,
					html: '',
					md: ''
				}
			},
			meta: {},
			access_grants: []
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		creating = false;

		if (!note) return;

		dispatch('create', note);
		close();
	};

	$: if (show) {
		loadNotes();
	}

	onMount(() => {
		if (show) {
			loadNotes();
		}
	});
</script>

<Modal bind:show size="sm" className="bg-white dark:bg-gray-900 rounded-3xl">
	<div class="flex flex-col max-h-[80vh]">
		<div class="px-5 py-4 border-b border-gray-100 dark:border-gray-800">
			<div class="text-lg font-medium text-gray-900 dark:text-gray-100">
				{$i18n.t('Select or Create Note')}
			</div>
			<div class="text-sm text-gray-500 dark:text-gray-400 mt-1">
				{$i18n.t('Choose a note to append recordings into.')}
			</div>
		</div>

		<div class="p-5 border-b border-gray-100 dark:border-gray-800 space-y-3">
			<label class="block text-sm text-gray-600 dark:text-gray-300" for="clara-note-title">
				{$i18n.t('Create Note')}
			</label>
			<div class="flex gap-2">
				<input
					id="clara-note-title"
					class="flex-1 rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-4 py-3 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600"
					type="text"
					bind:value={newNoteTitle}
					placeholder={$i18n.t('Clara')}
					on:keydown={(event) => {
						if (event.key === 'Enter') {
							createNote();
						}
					}}
				/>
				<button
					class="shrink-0 rounded-2xl bg-gray-900 text-white dark:bg-white dark:text-gray-900 px-4 py-3 text-sm font-medium disabled:opacity-60"
					on:click={createNote}
					disabled={creating}
				>
					{#if creating}
						<Spinner className="size-4" />
					{:else}
						<div class="flex items-center gap-2">
							<Plus className="size-4" />
							<span>{$i18n.t('Create')}</span>
						</div>
					{/if}
				</button>
			</div>
		</div>

		<div class="flex-1 overflow-y-auto p-3">
			{#if loading}
				<div class="flex justify-center py-12">
					<Spinner />
				</div>
			{:else if noteList.length === 0}
				<div class="text-sm text-center text-gray-500 dark:text-gray-400 py-12">
					{$i18n.t('No notes found')}
				</div>
			{:else}
				<div class="space-y-1">
					{#each noteList as note}
						<button
							class="w-full text-left rounded-2xl px-3 py-3 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
							on:click={() => selectNote(note)}
						>
							<div class="flex items-start gap-3">
								<div class="mt-0.5 text-gray-500 dark:text-gray-400">
									<Note className="size-4.5" />
								</div>
								<div class="min-w-0">
									<div class="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
										{note.title || $i18n.t('Untitled')}
									</div>
									<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
										{new Date(note.updated_at / 1000000).toLocaleString()}
									</div>
								</div>
							</div>
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</div>
</Modal>
