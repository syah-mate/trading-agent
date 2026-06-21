<script>
	let symbol = $state('XAUUSD');
	let lotSize = $state(0.01);
	let confidenceThreshold = $state(70);
	let sessions = $state({ London: true, NewYork: true, Overlap: true, Asia: false });
	let maxDailyLoss = $state(50);
	let llmModel = $state('google/gemini-2.0-flash-001');

	let saved = $state(false);
	let message = $state('');

	async function saveConfig() {
		const config = {
			symbol,
			lot_size: lotSize,
			confidence_threshold: confidenceThreshold,
			sessions,
			max_daily_loss: maxDailyLoss,
			llm_model: llmModel
		};
		try {
			// Simpan ke localStorage untuk sekarang
			localStorage.setItem('trading_agent_config', JSON.stringify(config));
			saved = true;
			message = '✅ Config saved to localStorage';
			setTimeout(() => { saved = false; message = ''; }, 3000);
		} catch (e) {
			message = '❌ Gagal save config';
		}
	}

	// Load from localStorage
	$effect(() => {
		try {
			const stored = localStorage.getItem('trading_agent_config');
			if (stored) {
				const c = JSON.parse(stored);
				symbol = c.symbol || symbol;
				lotSize = c.lot_size || lotSize;
				confidenceThreshold = c.confidence_threshold || confidenceThreshold;
				sessions = c.sessions || sessions;
				maxDailyLoss = c.max_daily_loss || maxDailyLoss;
				llmModel = c.llm_model || llmModel;
			}
		} catch (e) { /* ignore */ }
	});

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
	<div class="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-6">
		<!-- Symbol -->
		<div>
			<label class="text-sm text-gray-400 block mb-1">Symbol</label>
			<input type="text" bind:value={symbol} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none" />
		</div>

		<!-- Lot Size -->
		<div>
			<label class="text-sm text-gray-400 block mb-1">Lot Size</label>
			<input type="number" step="0.01" min="0.01" max="10" bind:value={lotSize} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none" />
		</div>

		<!-- Confidence Threshold -->
		<div>
			<label class="text-sm text-gray-400 block mb-1">Confidence Threshold: {confidenceThreshold}%</label>
			<input type="range" min="50" max="100" bind:value={confidenceThreshold} class="w-full accent-emerald-500" />
			<div class="flex justify-between text-xs text-gray-600">
				<span>50% (Aggressive)</span>
				<span>100% (Conservative)</span>
			</div>
		</div>

		<!-- Session Filter -->
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

		<!-- Max Daily Loss -->
		<div>
			<label class="text-sm text-gray-400 block mb-1">Max Daily Loss ($)</label>
			<input type="number" step="1" min="0" bind:value={maxDailyLoss} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none" />
		</div>

		<!-- LLM Model -->
		<div>
			<label class="text-sm text-gray-400 block mb-1">LLM Model</label>
			<select bind:value={llmModel} class="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none">
				{#each models as m}
					<option value={m}>{m}</option>
				{/each}
			</select>
		</div>

		<!-- Save Button -->
		<div class="flex items-center gap-4 pt-2">
			<button
				onclick={saveConfig}
				class="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm font-medium transition-colors"
			>
				💾 Save Configuration
			</button>
			{#if message}
				<span class="text-sm {saved ? 'text-emerald-400' : 'text-red-400'}">{message}</span>
			{/if}
		</div>
	</div>

	<!-- Info -->
	<div class="mt-8 p-4 bg-gray-900/50 border border-gray-800 rounded-lg">
		<h3 class="text-sm font-semibold text-gray-400 mb-2">ℹ️ Notes</h3>
		<ul class="text-xs text-gray-500 space-y-1">
			<li>• Config disimpan di localStorage browser ini</li>
			<li>• Untuk production, config akan disimpan ke MongoDB via API</li>
			<li>• Restart agent setelah mengubah config penting</li>
			<li>• Pastikan MT5 terminal running sebelum start agent</li>
		</ul>
	</div>
</div>
