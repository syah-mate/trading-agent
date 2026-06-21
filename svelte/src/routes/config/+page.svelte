<script>
	import { fetchConfig, updateConfig } from '$lib/api';

	let symbol = $state('XAUUSD');
	let lotSize = $state(0.01);
	let confidenceThreshold = $state(70);
	let sessions = $state({ London: true, NewYork: true, Overlap: true, Asia: false });
	let maxDailyLoss = $state(50);
	let llmModel = $state('google/gemini-2.0-flash-001');
	let loading = $state(true);
	let saving = $state(false);
	let message = $state('');
	let messageType = $state('');
	let rawConfig = $state(null);
	let showRaw = $state(false);

	$effect(() => {
		async function load() {
			try {
				const config = await fetchConfig();
				symbol = config.symbol || 'XAUUSD';
				lotSize = config.lot_size ?? 0.01;
				confidenceThreshold = config.confidence_threshold ?? 70;
				sessions = config.sessions || { London: true, NewYork: true, Overlap: true, Asia: false };
				maxDailyLoss = config.max_daily_loss ?? 50;
				llmModel = config.llm_model || 'google/gemini-2.0-flash-001';
				rawConfig = config;
			} catch (e) {
				message = '❌ Gagal load config: ' + (e.message || 'Unknown error');
				messageType = 'error';
			} finally {
				loading = false;
			}
		}
		load();
	});

	async function saveConfig() {
		saving = true;
		message = '';
		const config = {
			symbol,
			lot_size: lotSize,
			confidence_threshold: confidenceThreshold,
			sessions,
			max_daily_loss: maxDailyLoss,
			llm_model: llmModel
		};
		try {
			await updateConfig(config);
			messageType = 'success';
			message = '✅ Config berhasil disimpan';
			const updated = await fetchConfig();
			rawConfig = updated;
		} catch (e) {
			messageType = 'error';
			message = '❌ Gagal menyimpan: ' + (e.message || 'Unknown error');
		} finally {
			saving = false;
			setTimeout(() => { message = ''; messageType = ''; }, 3000);
		}
	}

	function toggleSession(key) {
		sessions = { ...sessions, [key]: !sessions[key] };
	}

	const models = [
		'google/gemini-2.0-flash-001',
		'google/gemini-2.5-pro-preview',
		'anthropic/claude-3-haiku',
		'meta-llama/llama-3-8b-instruct',
		'openai/gpt-4o-mini'
	];
</script>

<h1 class="text-2xl font-bold mb-6">Configuration</h1>

<div class="max-w-2xl">
	{#if loading}
		<div class="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-4 animate-pulse">
			<div class="h-5 bg-gray-800 rounded w-1/4"></div>
			<div class="h-10 bg-gray-800 rounded"></div>
			<div class="h-5 bg-gray-800 rounded w-1/4"></div>
			<div class="h-10 bg-gray-800 rounded"></div>
			<div class="h-5 bg-gray-800 rounded w-1/3"></div>
			<div class="h-8 bg-gray-800 rounded w-full"></div>
			<div class="h-5 bg-gray-800 rounded w-1/4"></div>
			<div class="h-10 bg-gray-800 rounded"></div>
			<div class="h-5 bg-gray-800 rounded w-1/4"></div>
			<div class="h-10 bg-gray-800 rounded"></div>
			<div class="h-10 bg-gray-800 rounded w-1/3"></div>
		</div>
	{:else}
		<div class="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-6">
			<div>
				<label class="text-sm text-gray-400 block mb-1">Symbol</label>
				<input type="text" bind:value={symbol} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none" />
			</div>

			<div>
				<label class="text-sm text-gray-400 block mb-1">Lot Size</label>
				<input type="number" step="0.01" min="0.01" max="10" bind:value={lotSize} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none" />
			</div>

			<div>
				<label class="text-sm text-gray-400 block mb-1">Confidence Threshold: {confidenceThreshold}%</label>
				<input type="range" min="50" max="100" bind:value={confidenceThreshold} class="w-full accent-emerald-500" />
				<div class="flex justify-between text-xs text-gray-600">
					<span>50% (Aggressive)</span>
					<span>100% (Conservative)</span>
				</div>
			</div>

			<div>
				<label class="text-sm text-gray-400 block mb-2">Session Filter</label>
				<div class="flex flex-wrap gap-2">
					{#each Object.entries(sessions) as [key, active]}
						<button
							onclick={() => toggleSession(key)}
							class="px-3 py-1.5 rounded-lg text-sm border transition-colors {active ? 'bg-emerald-900/30 border-emerald-700 text-emerald-300' : 'bg-gray-800 border-gray-700 text-gray-500'}"
						>
							{key}
						</button>
					{/each}
				</div>
			</div>

			<div>
				<label class="text-sm text-gray-400 block mb-1">Max Daily Loss ($)</label>
				<input type="number" step="1" min="0" bind:value={maxDailyLoss} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none" />
			</div>

			<div>
				<label class="text-sm text-gray-400 block mb-1">LLM Model</label>
				<select bind:value={llmModel} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none">
					{#each models as m}
						<option value={m}>{m}</option>
					{/each}
				</select>
			</div>

			<div class="flex items-center gap-4 pt-2">
				<button
					onclick={saveConfig}
					disabled={saving}
					class="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 disabled:text-gray-500 rounded-lg text-sm font-medium transition-colors"
				>
					{saving ? '💾 Menyimpan...' : '💾 Save Configuration'}
				</button>
				{#if message}
					<span class="text-sm {messageType === 'success' ? 'text-emerald-400' : 'text-red-400'}">{message}</span>
				{/if}
			</div>
		</div>

		<div class="mt-6">
			<button
				onclick={() => showRaw = !showRaw}
				class="px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-xs text-gray-400 transition-colors"
			>
				{showRaw ? 'Hide' : 'Show'} Current Config from API
			</button>
			{#if showRaw && rawConfig}
				<pre class="mt-3 bg-gray-900 border border-gray-800 rounded-lg p-4 text-xs text-gray-400 overflow-x-auto">{JSON.stringify(rawConfig, null, 2)}</pre>
			{/if}
		</div>
	{/if}

	<div class="mt-8 p-4 bg-gray-900/50 border border-gray-800 rounded-lg">
		<h3 class="text-sm font-semibold text-gray-400 mb-2">ℹ️ Notes</h3>
		<ul class="text-xs text-gray-500 space-y-1">
			<li>• Config disimpan di MongoDB dan akan digunakan agent secara real-time</li>
			<li>• Perubahan config langsung berlaku tanpa restart agent</li>
			<li>• Pastikan MT5 terminal running sebelum start agent</li>
		</ul>
	</div>
</div>
