<script>
	import { fetchConfig, updateConfig } from '$lib/api';

	let symbol = $state('XAUUSDc');
	let lotFix = $state(0.01);
	let confidenceThreshold = $state(70);
	let sessions = $state({ London: true, NewYork: true, Overlap: true, Asia: false });
	let maxDailyLoss = $state(50);
	let llmModel = $state('google/gemini-2.5-flash-lite');
	// Trading Parameters
	let tpMode = $state('fixed');
	let tpPips = $state(10.0);
	let slMode = $state('ai');
	let slPips = $state(10.0);
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
				symbol = config.symbol || 'XAUUSDc';
				lotFix = config.lot_fix ?? 0.01;
				confidenceThreshold = config.confidence_threshold ?? 70;
				sessions = config.sessions || { London: true, NewYork: true, Overlap: true, Asia: false };
				maxDailyLoss = config.max_daily_loss ?? 50;
				llmModel = config.llm_model || 'google/gemini-2.5-flash-lite';
				tpMode = config.tp_mode || 'fixed';
				tpPips = config.tp_pips ?? 10.0;
				slMode = config.sl_mode || 'ai';
				slPips = config.sl_pips ?? 10.0;
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
			lot_fix: lotFix,
			confidence_threshold: confidenceThreshold,
			sessions,
			max_daily_loss: maxDailyLoss,
			llm_model: llmModel,
			tp_mode: tpMode,
			tp_pips: tpPips,
			sl_mode: slMode,
			sl_pips: slPips,
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
		'openai/gpt-4o-mini',
		'x-ai/grok-4.3',
		'google/gemini-2.5-flash-lite'
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
				<label class="text-sm text-gray-400 block mb-1">Lot Size (Fixed)</label>
				<input type="number" step="0.01" min="0.01" max="10" bind:value={lotFix} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none" />
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

			<!-- Trading Parameters: TP & SL -->
			<div class="border-t border-gray-800 pt-4 mt-4">
				<h3 class="text-sm font-semibold text-emerald-400 mb-3">🎯 Take Profit & Stop Loss</h3>

				<!-- TP Mode -->
				<div class="mb-4">
					<label class="text-sm text-gray-400 block mb-2">TP Mode</label>
					<div class="flex gap-2">
						<button
							onclick={() => tpMode = 'fixed'}
							class="px-4 py-1.5 rounded-lg text-sm border transition-colors {tpMode === 'fixed' ? 'bg-emerald-900/30 border-emerald-700 text-emerald-300' : 'bg-gray-800 border-gray-700 text-gray-500'}"
						>
							Fixed (Pips)
						</button>
						<button
							onclick={() => tpMode = 'ai'}
							class="px-4 py-1.5 rounded-lg text-sm border transition-colors {tpMode === 'ai' ? 'bg-emerald-900/30 border-emerald-700 text-emerald-300' : 'bg-gray-800 border-gray-700 text-gray-500'}"
						>
							AI Decide
						</button>
					</div>
				</div>

				<!-- TP Pips (hanya muncul jika fixed) -->
				{#if tpMode === 'fixed'}
					<div class="mb-4">
						<label class="text-sm text-gray-400 block mb-1">
							TP Distance (pips) = {tpPips} pip
							<span class="text-gray-600"> ≈ ${(tpPips * 0.10).toFixed(2)} price move</span>
						</label>
						<input type="range" min="1" max="50" step="0.5" bind:value={tpPips} class="w-full accent-emerald-500" />
						<div class="flex justify-between text-xs text-gray-600">
							<span>1 pip ($0.10)</span>
							<span>50 pip ($5.00)</span>
						</div>
					</div>
				{/if}

				<!-- SL Mode -->
				<div class="mb-4">
					<label class="text-sm text-gray-400 block mb-2">SL Mode</label>
					<div class="flex gap-2">
						<button
							onclick={() => slMode = 'fixed'}
							class="px-4 py-1.5 rounded-lg text-sm border transition-colors {slMode === 'fixed' ? 'bg-emerald-900/30 border-emerald-700 text-emerald-300' : 'bg-gray-800 border-gray-700 text-gray-500'}"
						>
							Fixed (Pips)
						</button>
						<button
							onclick={() => slMode = 'ai'}
							class="px-4 py-1.5 rounded-lg text-sm border transition-colors {slMode === 'ai' ? 'bg-emerald-900/30 border-emerald-700 text-emerald-300' : 'bg-gray-800 border-gray-700 text-gray-500'}"
						>
							AI Decide
						</button>
					</div>
				</div>

				<!-- SL Pips (hanya muncul jika fixed) -->
				{#if slMode === 'fixed'}
					<div class="mb-4">
						<label class="text-sm text-gray-400 block mb-1">
							SL Distance (pips) = {slPips} pip
							<span class="text-gray-600"> ≈ ${(slPips * 0.10).toFixed(2)} price move</span>
						</label>
						<input type="range" min="1" max="50" step="0.5" bind:value={slPips} class="w-full accent-emerald-500" />
						<div class="flex justify-between text-xs text-gray-600">
							<span>1 pip ($0.10)</span>
							<span>50 pip ($5.00)</span>
						</div>
					</div>
				{/if}
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
