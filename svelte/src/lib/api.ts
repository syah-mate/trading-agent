// API client untuk FastAPI backend
// TASK 7.1

const API_BASE = 'http://localhost:8000';

async function fetchJSON(url: string, options?: RequestInit) {
	const res = await fetch(url, options);
	if (!res.ok) {
		const text = await res.text();
		throw new Error(`API error ${res.status}: ${text}`);
	}
	return res.json();
}

// ---- Status ----
export async function fetchStatus() {
	return fetchJSON(`${API_BASE}/status`);
}

// ---- Trades ----
export async function fetchTrades(limit = 50, skip = 0) {
	return fetchJSON(`${API_BASE}/trades?limit=${limit}&skip=${skip}`);
}

export async function fetchTradeByTicket(ticket: number) {
	return fetchJSON(`${API_BASE}/trades/${ticket}`);
}

// ---- Signals ----
export async function fetchSignals(limit = 50) {
	return fetchJSON(`${API_BASE}/signals?limit=${limit}`);
}

// ---- Backtest ----
export async function fetchBacktestRuns() {
	return fetchJSON(`${API_BASE}/backtest/runs`);
}

export async function fetchBacktestRun(runId: string) {
	return fetchJSON(`${API_BASE}/backtest/runs/${runId}`);
}

export async function fetchBacktestProgress(runId: string) {
	return fetchJSON(`${API_BASE}/backtest/runs/${runId}/progress`);
}

export async function startBacktest(params: {
	symbol: string;
	timeframe: string;
	months_back: number;
	lot_size: number;
}) {
	return fetchJSON(`${API_BASE}/backtest/start`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(params)
	});
}

// ---- Config ----
export async function fetchConfig() {
	return fetchJSON(`${API_BASE}/config`);
}

export async function updateConfig(config: Record<string, unknown>) {
	return fetchJSON(`${API_BASE}/config`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(config)
	});
}

// ---- Agent Control ----
export async function startAgent() {
	return fetchJSON(`${API_BASE}/agent/start`, { method: 'POST' });
}

export async function stopAgent() {
	return fetchJSON(`${API_BASE}/agent/stop`, { method: 'POST' });
}
