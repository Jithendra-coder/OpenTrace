// ─── OpenTrace Noir Web Application ──────────────────────────────────────────

// ── API Layer ─────────────────────────────────────────────────────────────────
const API = {
  async get(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json();
  },
  async post(path, body = {}) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json();
  },
  async delete(path) {
    const r = await fetch(path, { method: 'DELETE' });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json();
  },
};

// ── State ─────────────────────────────────────────────────────────────────────
const State = {
  ws: null,
  page: 'overview',
  loading: false,
  projects: [],
  activeProjectId: null,
};

// ── Toast Notification (Strictly for Major Actions & Errors) ──────────────────
function toast(msg, type = 'success') {
  const el = document.createElement('div');
  const styles = {
    success: 'background:#000000;color:#FFFFFF;border:1px solid #27272A;',
    error:   'background:#FEF2F2;color:#991B1B;border:1px solid #FECACA;',
    info:    'background:#F4F4F5;color:#18181B;border:1px solid #E4E4E7;',
    warn:    'background:#FFFBEB;color:#92400E;border:1px solid #FDE68A;',
  };
  el.className = 'toast';
  el.style.cssText = styles[type] || styles.success;
  el.textContent = msg;
  const container = document.getElementById('toast-container');
  if (container) container.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

// ── Router with URL Hash Persistence ──────────────────────────────────────────
const PAGES = {
  overview:   { title: 'Migration Dashboard', sub: 'Real-time overview of your migration workspace & blast radius', render: renderOverview },
  analyze:    { title: 'Analyze',  sub: 'Compare OpenAPI specs and scan repository for affected code', render: renderAnalyze },
  migrate:    { title: 'Migrate',  sub: 'Generate a migration plan with RouteForge engine', render: renderMigrate },
  validate:   { title: 'Validate', sub: 'Test the proposed patch in an isolated ephemeral sandbox', render: renderValidate },
  playground: { title: 'API Simulator', sub: 'Interactive breaking change simulator with live visual graph', render: renderPlayground },
  pr:         { title: 'Pull Requests', sub: 'Open a draft GitHub PR for your migration', render: renderPR },
  feedback:   { title: 'Audit & Decision Log', sub: 'Comprehensive audit trail of migration decisions & patch verification', render: renderFeedback },
  guide:      { title: 'Workflow Guide', sub: 'Step-by-step CLI & Web migration workflow guide', render: renderGuide },
  settings:   { title: 'Settings', sub: 'Environment, Python runtime, RouteForge intelligence & safety', render: renderSettings },
};

function getInitialPage() {
  const hash = window.location.hash ? window.location.hash.replace('#', '').trim() : '';
  return PAGES[hash] ? hash : 'overview';
}

function navigate(page, updateHash = true) {
  if (!PAGES[page]) page = 'overview';
  State.page = page;
  if (updateHash && window.location.hash.replace('#', '') !== page) {
    window.location.hash = page;
  }
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.page === page);
  });
  const p = PAGES[page];
  const titleEl = document.getElementById('page-title');
  const subEl = document.getElementById('page-sub');
  if (titleEl) titleEl.textContent = p.title;
  if (subEl) subEl.textContent = p.sub;
  const content = document.getElementById('page-content');
  if (content) {
    content.style.opacity = '0';
    setTimeout(() => {
      content.innerHTML = p.render(State.ws);
      content.style.opacity = '1';
      content.style.transition = 'opacity 0.12s ease-out';
    }, 40);
  }
}

// ── Data Loading ──────────────────────────────────────────────────────────────
async function loadWorkspace() {
  try {
    try {
      const projData = await API.get('/api/projects');
      State.projects = projData?.projects || [];
      State.activeProjectId = projData?.active_id || null;
      const pSel = document.getElementById('project-select');
      if (pSel && State.projects.length > 0) {
        pSel.innerHTML = State.projects.map(p => 
          `<option value="${p.id}" ${p.id === State.activeProjectId ? 'selected' : ''}>${p.name}</option>`
        ).join('');
      }
    } catch (_) {}

    State.ws = await API.get('/api/workspace');
    const dot = document.getElementById('status-dot');
    if (dot) {
      dot.innerHTML = `<span class="w-2 h-2 rounded-full" style="background:#10B981;"></span> <span class="text-neutral-900 font-medium">Connected</span>`;
    }
    const ws = State.ws;
    const wsPath = ws?.workspace || '—';
    const wsEl = document.getElementById('ws-path');
    if (wsEl) {
      wsEl.textContent = wsPath.length > 30 ? '…' + wsPath.slice(-28) : wsPath;
      wsEl.title = wsPath;
    }
  } catch (e) {
    State.ws = null;
    const dot = document.getElementById('status-dot');
    if (dot) {
      dot.innerHTML = `<span class="w-2 h-2 rounded-full bg-red-500"></span> <span class="text-red-600 font-medium">Disconnected</span>`;
    }
  }
  navigate(State.page, false);
}

// ─── Pages ────────────────────────────────────────────────────────────────────

// ── 1. Overview ───────────────────────────────────────────────────────────────
function renderOverview(ws) {
  const a  = ws?.analysis   || {};
  const p  = ws?.plan       || {};
  const v  = ws?.validation || {};
  const pr = ws?.pr_audit   || null;

  const changesCount  = a.changes_count  ?? (a.changes ? a.changes.length : '—');
  const directCount   = a.direct_count   ?? (a.direct_impacts ? a.direct_impacts.length : '—');
  const valStatus     = v.status         || '—';
  const prCount       = pr ? 1 : 0;

  const hasAnalysis = Boolean(a && (a.changes_count > 0 || (a.changes && a.changes.length > 0) || a.old_spec));

  let html = `
    <!-- Top Metric Cards (Prominent 4-card overview with colored accents) -->
    <div class="grid grid-cols-4 gap-4 mb-6">
      ${C.statCard('Breaking Changes', changesCount, a.old_spec ? `${a.old_spec.split(/[/\\]/).pop()} → ${a.new_spec?.split(/[/\\]/).pop()}` : 'No contract diff loaded', 'red')}
      ${C.statCard('Files Affected',   directCount, directCount !== '—' ? `${a.indirect_count ?? 0} indirect callers` : 'Scan repo in Analyze', 'amber')}
      ${C.statCard('Validation',       valStatus === '—' ? '—' : '', valStatus !== '—' ? C.statusBadge(valStatus) : 'Ephemeral sandbox idle', 'slate')}
      ${C.statCard('Open PRs',         prCount, pr ? `Branch: ${pr.branch?.split('/').pop() || '—'}` : 'No PR open', 'slate')}
    </div>
  `;

  if (!hasAnalysis) {
    html += `
      <div class="card p-8 text-center bg-white border border-neutral-200 mb-6">
        <div class="w-12 h-12 rounded-2xl bg-neutral-100 border border-neutral-200 flex items-center justify-center mx-auto mb-4 text-neutral-800">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        </div>
        <h3 class="text-lg font-bold text-black tracking-tight mb-1">No Active Migration Analysis</h3>
        <p class="text-[13px] text-neutral-500 max-w-md mx-auto mb-6">
          Choose a scenario below to load pre-configured OpenAPI contracts and trace caller impact:
        </p>
        <div class="grid grid-cols-3 gap-4 max-w-3xl mx-auto text-left">
          <div class="card p-4 hover:border-black transition-all cursor-pointer bg-neutral-50/60" onclick="App.runPreset('sample1')">
            <div class="flex items-center justify-between mb-2">
              <span class="text-[11px] font-bold uppercase tracking-wider text-neutral-400">Sample 1</span>
              <span class="badge" style="background:#000000;color:#fff;">1-Click</span>
            </div>
            <div class="font-bold text-[13.5px] text-black">Payments API</div>
            <div class="text-[11.5px] text-neutral-500 mt-1 mb-3">Field rename (<code class="text-neutral-800">amount</code> → <code class="text-neutral-800">price_cents</code>).</div>
            <button class="btn btn-secondary text-[12px] w-full justify-center">Run Sample 1</button>
          </div>

          <div class="card p-4 hover:border-black transition-all cursor-pointer bg-neutral-50/60" onclick="App.runPreset('sample2')">
            <div class="flex items-center justify-between mb-2">
              <span class="text-[11px] font-bold uppercase tracking-wider text-neutral-400">Sample 2</span>
              <span class="badge" style="background:#000000;color:#fff;">1-Click</span>
            </div>
            <div class="font-bold text-[13.5px] text-black">Enterprise Billing</div>
            <div class="text-[11.5px] text-neutral-500 mt-1 mb-3">Invoice status enum & customer ID type mismatch.</div>
            <button class="btn btn-secondary text-[12px] w-full justify-center">Run Sample 2</button>
          </div>

          <div class="card p-4 hover:border-black transition-all cursor-pointer bg-neutral-50/60" onclick="App.runPreset('demo')">
            <div class="flex items-center justify-between mb-2">
              <span class="text-[11px] font-bold uppercase tracking-wider text-neutral-400">Demo</span>
              <span class="badge" style="background:#000000;color:#fff;">1-Click</span>
            </div>
            <div class="font-bold text-[13.5px] text-black">E-Commerce Store</div>
            <div class="text-[11.5px] text-neutral-500 mt-1 mb-3">Checkout service ripple across multiple microservices.</div>
            <button class="btn btn-secondary text-[12px] w-full justify-center">Run Demo Store</button>
          </div>
        </div>
      </div>
    `;
    return html;
  }

  // Visual Call Graph
  html += C.visualCallGraph(a.direct_impacts || [], a.indirect_symbols || [], a.changes || []);

  // Runtime Failure Diagnostics (If changes exist)
  if (a.changes && a.changes.length > 0) {
    html += C.runtimeDiagnostic(a.changes, a.direct_impacts);
  }

  html += `
    <div class="grid grid-cols-3 gap-6">
      <!-- Left 2/3: Changes & Migration Plan -->
      <div class="col-span-2 space-y-6">`;

  // API Changes Table
  const changes = a.changes || [];
  html += `
        <div class="card overflow-hidden">
          <div class="px-6 pt-5 pb-3 flex items-center justify-between border-b border-neutral-100">
            <div>
              <div class="text-[14px] font-bold text-black">API Changes Detected</div>
              <div class="text-[12px] text-neutral-400 mt-0.5">${changes.length} breaking change${changes.length !== 1 ? 's' : ''}</div>
            </div>
            <button class="btn btn-secondary text-[12px]" onclick="navigate('analyze')">Re-analyze</button>
          </div>`;

  if (changes.length === 0) {
    html += `<div class="p-6">${C.cleanContractCard()}</div>`;
  } else {
    html += `
          <table>
            <thead><tr>
              <th>Method</th><th>Endpoint Path</th><th>Classification</th><th>Target Field</th><th>Status</th>
            </tr></thead>
            <tbody>`;
    changes.forEach(c => {
      html += `<tr>
        <td>${C.methodBadge(c.method)}</td>
        <td class="font-mono text-[12.5px] text-neutral-800">${c.path || '—'}</td>
        <td>${C.badge('BREAKING', 'red')}</td>
        <td class="font-mono text-[12px] text-neutral-600">${c.field || '—'}</td>
        <td>${C.badge('Detected', 'gray')}</td>
      </tr>`;
    });
    html += `</tbody></table>`;
  }
  html += `</div>`;

  // Migration Plan Table
  const edits = p.patch?.edits || [];
  html += `
        <div class="card overflow-hidden">
          <div class="px-6 pt-5 pb-3 flex items-center justify-between border-b border-neutral-100">
            <div>
              <div class="text-[14px] font-bold text-black">Migration Plan</div>
              <div class="text-[12px] text-neutral-400 mt-0.5">${edits.length} edit${edits.length !== 1 ? 's' : ''} &bull; ${p.policy || 'balanced'} policy</div>
            </div>
            ${p.generation_status ? C.statusBadge(p.generation_status) : ''}
          </div>`;

  if (edits.length === 0) {
    html += `<div class="p-6 text-center">
      <div class="text-[13px] text-neutral-500 mb-3">No migration plan generated yet.</div>
      <button class="btn btn-primary" onclick="navigate('migrate')">Generate Migration Plan</button>
    </div>`;
  } else {
    html += `<table><thead><tr><th>Target File</th><th>Symbol</th><th>Strategy</th><th>Risk</th><th>Reason</th></tr></thead><tbody>`;
    edits.forEach(e => {
      html += `<tr>
        <td class="font-mono text-[12.5px] text-black font-medium">${e.file || '—'}</td>
        <td class="font-mono text-[11.5px] text-neutral-500">${e.symbol ? e.symbol.split('::').pop() : '—'}</td>
        <td>${C.badge(p.selected_strategy || 'SMALL', 'slate')}</td>
        <td>${C.riskBadge(p.selected_strategy || 'SMALL')}</td>
        <td class="text-[12px] text-neutral-600 max-w-xs truncate">${e.reason || '—'}</td>
      </tr>`;
      if (e.expected_original_text || e.replacement_text) {
        html += `<tr style="background:#FAFAFA;"><td colspan="5" class="px-5 pb-3">${C.diff(e.expected_original_text, e.replacement_text)}</td></tr>`;
      }
    });
    html += `</tbody></table>`;
  }
  html += `</div></div>`;

  // Right 1/3: Validation Evidence & Quick Actions
  html += `
      <div class="space-y-6">
        <!-- Validation Evidence -->
        <div class="card p-5">
          <div class="text-[14px] font-bold text-black mb-3">Validation Proof</div>
          ${v.status ? C.validationDiagnostic(v) : C.banner('Run Validate to execute regression tests in sandbox.', 'info')}
          <div class="space-y-1">
            ${C.checkRow('Sandbox Workspace', null, v.workspace_created ?? null)}
            ${C.checkRow('Patch Applied', null, v.patch_applied ?? null)}
            ${C.checkRow('Python AST Syntax', null, v.syntax_ok ?? null)}
            ${v.tests_collected !== undefined ? C.checkRow('Tests Collected', v.tests_collected, null) : ''}
            ${v.tests_passed   !== undefined ? C.checkRow('Tests Passed',   v.tests_passed,   v.tests_passed > 0) : ''}
            ${v.tests_failed   !== undefined && v.tests_failed > 0 ? C.checkRow('Tests Failed', v.tests_failed, false) : ''}
            ${v.duration_ms    !== undefined ? C.checkRow('Duration', v.duration_ms + 'ms', null) : ''}
          </div>
          ${v.status ? `<div class="mt-4 pt-3 border-t border-neutral-100 flex items-center justify-between"><span class="text-[12.5px] text-neutral-600 font-medium">Status</span>${C.statusBadge(v.status)}</div>` : ''}
          ${v.failure_summary ? `<div class="mt-3">${C.code(v.failure_summary)}</div>` : ''}
        </div>

        <!-- Quick Actions -->
        <div class="card p-5">
          <div class="text-[14px] font-bold text-black mb-3">Quick Actions</div>
          <div class="space-y-2">
            <button class="btn btn-primary w-full justify-center" onclick="navigate('analyze')">Run Analysis</button>
            <button class="btn btn-secondary w-full justify-center" onclick="navigate('migrate')">Run Migrate</button>
            <button class="btn btn-secondary w-full justify-center" onclick="navigate('validate')">Run Validate</button>
            <button class="btn btn-secondary w-full justify-center" onclick="App.exportReport()">Export Migration Report</button>
          </div>
        </div>
      </div>
    </div>
  `;

  return html;
}

// ── 2. Analyze ────────────────────────────────────────────────────────────────
function renderAnalyze(ws) {
  const a = ws?.analysis;
  const oldSpec = a?.old_spec || 'sample1/api_v1.yaml';
  const newSpec = a?.new_spec || 'sample1/api_v2.yaml';
  const repo    = a?.repo    || 'sample1';

  return `
    <div class="max-w-4xl mx-auto space-y-6">

      <!-- Preset Sample Selector (1-Click) -->
      <div class="card p-6">
        <div class="text-[15px] font-bold text-black tracking-tight mb-1">Select Sample Scenarios (1-Click Pre-fill & Run)</div>
        <div class="text-[12.5px] text-neutral-500 mb-4">Click any sample below to load its OpenAPI specs and target code:</div>

        <div class="grid grid-cols-3 gap-4">
          <div class="p-4 rounded-xl border border-neutral-200 hover:border-black transition-all bg-neutral-50/50 cursor-pointer" onclick="App.setAnalyzePreset('sample1')">
            <div class="flex items-center justify-between mb-1.5">
              <span class="font-bold text-[13px] text-black">Sample 1: Payments</span>
              <span class="badge" style="background:#000;color:#fff;">Select</span>
            </div>
            <div class="text-[11.5px] text-neutral-500 leading-snug">
              Old: <code>sample1/api_v1.yaml</code><br>
              New: <code>sample1/api_v2.yaml</code><br>
              Repo: <code>sample1</code>
            </div>
            <div class="text-[11px] text-neutral-400 mt-2">Field rename in request payload.</div>
          </div>

          <div class="p-4 rounded-xl border border-neutral-200 hover:border-black transition-all bg-neutral-50/50 cursor-pointer" onclick="App.setAnalyzePreset('sample2')">
            <div class="flex items-center justify-between mb-1.5">
              <span class="font-bold text-[13px] text-black">Sample 2: Billing</span>
              <span class="badge" style="background:#000;color:#fff;">Select</span>
            </div>
            <div class="text-[11.5px] text-neutral-500 leading-snug">
              Old: <code>sample2/api_v1.yaml</code><br>
              New: <code>sample2/api_v2.yaml</code><br>
              Repo: <code>sample2</code>
            </div>
            <div class="text-[11px] text-neutral-400 mt-2">Enum and customer ID type change.</div>
          </div>

          <div class="p-4 rounded-xl border border-neutral-200 hover:border-black transition-all bg-neutral-50/50 cursor-pointer" onclick="App.setAnalyzePreset('demo')">
            <div class="flex items-center justify-between mb-1.5">
              <span class="font-bold text-[13px] text-black">Demo: Store</span>
              <span class="badge" style="background:#000;color:#fff;">Select</span>
            </div>
            <div class="text-[11.5px] text-neutral-500 leading-snug">
              Old: <code>demo/payment_api_v1.yaml</code><br>
              New: <code>demo/payment_api_v2.yaml</code><br>
              Repo: <code>demo/ecommerce</code>
            </div>
            <div class="text-[11px] text-neutral-400 mt-2">Multi-caller ripple impact.</div>
          </div>
        </div>
      </div>

      <!-- Manual File & Folder Inputs -->
      <div class="card p-6">
        ${C.sectionHead('Analyze API Contract Differences', 'Specify your baseline specification, updated specification, and target repository.')}

        <div class="space-y-4">
          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="form-label mb-0">Old Spec Path (v1 Baseline)</label>
              <label class="text-[11px] font-semibold text-neutral-800 hover:text-black hover:underline cursor-pointer">
                Browse File
                <input type="file" accept=".yaml,.yml,.json" class="hidden" onchange="App.handleAnalyzeBrowse(this, 'a-old')" />
              </label>
            </div>
            <input id="a-old" class="input font-mono text-[12px]" placeholder="e.g. sample1/api_v1.yaml" value="${oldSpec}" />
            <div class="text-[11px] text-neutral-400 mt-1">Relative or absolute path to the previous OpenAPI specification (.yaml or .json)</div>
          </div>

          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="form-label mb-0">New Spec Path (v2 Target)</label>
              <label class="text-[11px] font-semibold text-neutral-800 hover:text-black hover:underline cursor-pointer">
                Browse File
                <input type="file" accept=".yaml,.yml,.json" class="hidden" onchange="App.handleAnalyzeBrowse(this, 'a-new')" />
              </label>
            </div>
            <input id="a-new" class="input font-mono text-[12px]" placeholder="e.g. sample1/api_v2.yaml" value="${newSpec}" />
            <div class="text-[11px] text-neutral-400 mt-1">Relative or absolute path to the modified/new OpenAPI specification (.yaml or .json)</div>
          </div>

          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="form-label mb-0">Repository Directory Path</label>
              <label class="text-[11px] font-semibold text-neutral-800 hover:text-black hover:underline cursor-pointer">
                Browse Folder
                <input type="file" webkitdirectory directory class="hidden" onchange="App.handleAnalyzeRepoBrowse(this)" />
              </label>
            </div>
            <input id="a-repo" class="input font-mono text-[12px]" placeholder="e.g. sample1, src, or https://github.com/..." value="${repo}" />
            <div class="text-[11px] text-neutral-400 mt-1">Local codebase path (e.g. <code>sample1</code>) or GitHub repo URL (e.g. <code>https://github.com/Jithendra-coder/OpenTrace.git</code>)</div>
          </div>

          <div class="flex items-center gap-3 pt-2">
            <button class="btn btn-primary" id="analyze-btn" onclick="runAnalyze()">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              Run Analysis
            </button>
            <button class="btn btn-secondary text-[12.5px]" onclick="App.copyCurrentCliCommand()">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
              Copy CLI Command
            </button>
          </div>
        </div>
      </div>

      <!-- Runtime Failure Diagnostics -->
      ${a && a.changes && a.changes.length > 0 ? C.runtimeDiagnostic(a.changes, a.direct_impacts) : ''}

      <!-- Results Display -->
      ${a ? (a.changes_count === 0 && (!a.changes || a.changes.length === 0) ? C.cleanContractCard() : `
        <div class="card overflow-hidden">
          <div class="px-6 pt-5 pb-3 border-b border-neutral-100 flex items-center justify-between">
            <div>
              <div class="text-[14px] font-bold text-black">Analysis Results</div>
              <div class="text-[12px] text-neutral-400 mt-0.5">${a.changes_count || a.changes?.length || 0} breaking change(s) &bull; ${a.direct_count || 0} direct &bull; ${a.indirect_count || 0} indirect callers</div>
            </div>
            <button class="btn btn-primary text-[12px]" onclick="navigate('migrate')">Proceed to Migrate</button>
          </div>
          <table>
            <thead><tr><th>Method</th><th>Endpoint</th><th>Type</th><th>Field</th></tr></thead>
            <tbody>
              ${(a.changes || []).map(c => `
                <tr>
                  <td>${C.methodBadge(c.method)}</td>
                  <td class="font-mono text-[12.5px]">${c.path}</td>
                  <td>${C.badge('BREAKING', 'red')}</td>
                  <td class="font-mono text-[12px] text-neutral-500">${c.field || '—'}</td>
                </tr>`).join('')}
            </tbody>
          </table>
          <div class="px-6 pt-4 pb-5 border-t border-neutral-100">
            <div class="text-[12px] font-semibold text-neutral-600 mb-2.5">Affected Code Locations</div>
            <div class="space-y-2">
              ${(a.direct_impacts || []).map(i => `
                <div class="flex items-center gap-2 font-mono text-[12px] text-neutral-800 bg-neutral-50 px-3 py-1.5 rounded-lg border border-neutral-200">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/></svg>
                  <span class="font-semibold text-black">${i.file}${i.line ? ':' + i.line : ''}</span>
                  ${i.symbol ? `<span class="text-neutral-500">::${i.symbol.split('::').pop()}</span>` : ''}
                  <span class="ml-auto">${C.badge('DIRECT', 'black')}</span>
                </div>`).join('')}
            </div>
          </div>
        </div>`) : ''}
    </div>`;
}

async function runAnalyze() {
  const btn = document.getElementById('analyze-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Running analysis…';
  }
  const oldPath = document.getElementById('a-old').value.trim();
  const newPath = document.getElementById('a-new').value.trim();
  const repoPath = document.getElementById('a-repo').value.trim();

  try {
    await API.post('/api/analyze', {
      old_spec: oldPath,
      new_spec: newPath,
      repo:     repoPath,
    });
    toast('Analysis complete', 'success');
    await loadWorkspace();
  } catch (e) {
    toast('Analysis failed: ' + e.message, 'error');
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Run Analysis';
    }
  }
}

// ── 3. Migrate ────────────────────────────────────────────────────────────────
function renderMigrate(ws) {
  const p = ws?.plan;
  const a = ws?.analysis;
  if (!a || (!a.changes && !a.changes_count)) return C.emptyState(
    `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/></svg>`,
    'Run Analyze first',
    'Migration requires an active analysis. Go to Analyze to detect API contract changes.',
    `<button class="btn btn-primary" onclick="navigate('analyze')">Go to Analyze</button>`
  );

  const activePolicy = p?.policy || 'balanced';
  const edits = p?.patch?.edits || [];

  return `
    <div class="max-w-3xl mx-auto space-y-6">
      <div class="card p-6">
        ${C.sectionHead('Generate Migration Plan with RouteForge', 'RouteForge evaluates AST repair strategies to resolve breaking contract changes safely.')}
        <div class="mb-5">
          <label class="form-label mb-2">Routing Policy</label>
          <div class="grid grid-cols-3 gap-3">
            <label class="policy-option ${activePolicy === 'economy' ? 'active' : ''}" style="${activePolicy === 'economy' ? 'border-color:#000;background:#F4F4F5;' : 'border-color:#E4E4E7;background:#fff;'}">
              <div class="flex items-center justify-between mb-1">
                <span class="policy-title text-[13.5px] font-semibold text-black">Economy</span>
                <input type="radio" name="policy" value="economy" ${activePolicy === 'economy' ? 'checked' : ''} onchange="App.handlePolicy(this)" class="accent-black w-4 h-4 cursor-pointer" />
              </div>
              <span class="policy-desc text-[11px] text-neutral-500">Minimal token usage, deterministic templates</span>
            </label>

            <label class="policy-option ${activePolicy === 'balanced' ? 'active' : ''}" style="${activePolicy === 'balanced' ? 'border-color:#000;background:#F4F4F5;' : 'border-color:#E4E4E7;background:#fff;'}">
              <div class="flex items-center justify-between mb-1">
                <span class="policy-title text-[13.5px] font-semibold text-black">Balanced</span>
                <input type="radio" name="policy" value="balanced" ${activePolicy === 'balanced' ? 'checked' : ''} onchange="App.handlePolicy(this)" class="accent-black w-4 h-4 cursor-pointer" />
              </div>
              <span class="policy-desc text-[11px] text-neutral-500">Default &bull; Bounded candidates with validation</span>
            </label>

            <label class="policy-option ${activePolicy === 'comprehensive' ? 'active' : ''}" style="${activePolicy === 'comprehensive' ? 'border-color:#000;background:#F4F4F5;' : 'border-color:#E4E4E7;background:#fff;'}">
              <div class="flex items-center justify-between mb-1">
                <span class="policy-title text-[13.5px] font-semibold text-black">Comprehensive</span>
                <input type="radio" name="policy" value="comprehensive" ${activePolicy === 'comprehensive' ? 'checked' : ''} onchange="App.handlePolicy(this)" class="accent-black w-4 h-4 cursor-pointer" />
              </div>
              <span class="policy-desc text-[11px] text-neutral-500">Deep structural AST refactoring</span>
            </label>
          </div>
        </div>

        <div class="flex items-center gap-3">
          <button class="btn btn-primary" id="migrate-btn" onclick="runMigrate()">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/></svg>
            Generate Plan
          </button>
        </div>
      </div>

      ${edits.length > 0 ? `
        <div class="card overflow-hidden">
          <div class="px-6 pt-5 pb-3 flex items-center justify-between border-b border-neutral-100">
            <div>
              <div class="text-[14px] font-bold text-black">Generated Patches (${edits.length})</div>
              <div class="text-[12px] text-neutral-400 mt-0.5">Strategy: ${p.selected_strategy || 'SMALL'} &bull; Status: ${p.generation_status || 'GENERATED'}</div>
            </div>
            <div class="flex items-center gap-2">
              <button class="btn btn-secondary text-[12px]" onclick="App.applyPatch()">Apply Directly</button>
              <button class="btn btn-primary text-[12px]" onclick="navigate('validate')">Test in Sandbox</button>
            </div>
          </div>
          <table>
            <thead><tr><th>Target File</th><th>Symbol</th><th>Strategy</th><th>Risk</th></tr></thead>
            <tbody>
              ${edits.map(e => `
                <tr>
                  <td class="font-mono text-[12.5px] text-black font-semibold">${e.file}</td>
                  <td class="font-mono text-[11.5px] text-neutral-500">${e.symbol ? e.symbol.split('::').pop() : '—'}</td>
                  <td>${C.badge(p.selected_strategy || 'SMALL', 'slate')}</td>
                  <td>${C.riskBadge(p.selected_strategy || 'SMALL')}</td>
                </tr>
                <tr style="background:#FAFAFA;"><td colspan="4" class="px-5 pb-3">${C.diff(e.expected_original_text, e.replacement_text)}</td></tr>
              `).join('')}
            </tbody>
          </table>
        </div>` : ''}
    </div>`;
}

async function runMigrate() {
  const btn = document.getElementById('migrate-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Generating plan…';
  }
  const policy = document.querySelector('input[name="policy"]:checked')?.value || 'balanced';
  try {
    await API.post('/api/migrate', { policy });
    toast('Migration plan generated', 'success');
    await loadWorkspace();
  } catch (e) {
    toast('Migration failed: ' + e.message, 'error');
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Generate Plan';
    }
  }
}

// ── 4. Validate ───────────────────────────────────────────────────────────────
function renderValidate(ws) {
  const v = ws?.validation;
  const p = ws?.plan;

  return `
    <div class="max-w-4xl mx-auto space-y-6">
      <div class="card p-6">
        ${C.sectionHead('Sandbox Patch Validation', 'Verify patches in an isolated ephemeral filesystem before applying changes.')}
        <div class="text-[13px] text-neutral-600 mb-5 leading-relaxed">
          OpenTrace copies your code to a clean temporary sandbox directory, applies candidate diffs, checks Python AST syntax with <code class="font-mono text-black font-medium">ast.parse()</code>, and executes pytest test suites. Your working directory remains completely untouched until you confirm.
        </div>

        <div class="flex items-center gap-3">
          <button class="btn btn-primary" id="validate-btn" onclick="runValidate()">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            Execute Sandbox Validation
          </button>
        </div>
      </div>

      ${v ? `
        <div class="card p-6">
          <div class="flex items-center justify-between mb-4">
            <div class="text-[15px] font-bold text-black">Sandbox Test Results</div>
            ${C.statusBadge(v.status || 'TESTS_PASSED')}
          </div>
          ${C.validationDiagnostic(v)}

          <div class="space-y-2 border-t border-neutral-100 pt-4">
            ${C.checkRow('Sandbox Creation', null, v.workspace_created ?? true)}
            ${C.checkRow('Patch Cleanly Applied', null, v.patch_applied ?? true)}
            ${C.checkRow('Python AST Syntax Check', null, v.syntax_ok ?? true)}
            ${v.tests_collected !== undefined ? C.checkRow('Tests Collected', v.tests_collected, null) : ''}
            ${v.tests_passed !== undefined ? C.checkRow('Tests Passed', v.tests_passed, v.tests_passed > 0) : ''}
            ${v.duration_ms !== undefined ? C.checkRow('Execution Duration', v.duration_ms + 'ms', null) : ''}
          </div>

          ${v.failure_summary ? `<div class="mt-4">${C.code(v.failure_summary)}</div>` : ''}

          <div class="mt-6 pt-4 border-t border-neutral-100 flex items-center justify-between">
            <span class="text-[13px] text-neutral-600 font-medium">Validation completed. Apply verified patches to files?</span>
            <div class="flex items-center gap-2.5">
              <button class="btn btn-secondary text-[12.5px]" onclick="navigate('pr')">Open Draft PR</button>
              <button class="btn btn-primary text-[12.5px]" onclick="App.applyPatch()">Apply to Codebase</button>
            </div>
          </div>
        </div>` : ''}
    </div>`;
}

async function runValidate() {
  const btn = document.getElementById('validate-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Validating in sandbox…';
  }
  try {
    await API.post('/api/validate', {});
    toast('Sandbox validation complete', 'success');
    await loadWorkspace();
  } catch (e) {
    toast('Validation failed: ' + e.message, 'error');
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Execute Sandbox Validation';
    }
  }
}

// ── 5. Pull Requests ──────────────────────────────────────────────────────────
function renderPR(ws) {
  const pr = ws?.pr_audit;
  const p  = ws?.plan;

  return `
    <div class="max-w-3xl mx-auto space-y-6">
      <div class="card p-6">
        ${C.sectionHead('Create GitHub Draft Pull Request', 'Submit generated patches as an audited, reversible draft pull request.')}

        <div class="space-y-4">
          <div>
            <label class="form-label">Target Base Branch</label>
            <input id="pr-base" class="input font-mono text-[12px]" placeholder="main" value="main" />
          </div>

          <div>
            <label class="form-label">GitHub Access Token (Optional for dry-run)</label>
            <input id="pr-token" type="password" class="input font-mono text-[12px]" placeholder="ghp_xxxxxxxxxxxx" />
            <div class="text-[11px] text-neutral-400 mt-1">Leave empty to perform a local dry-run preview.</div>
          </div>

          <div class="flex items-center gap-2 pt-1">
            <input id="pr-dryrun" type="checkbox" checked class="w-4 h-4 accent-black rounded cursor-pointer" />
            <label for="pr-dryrun" class="text-[13px] text-neutral-700 font-medium cursor-pointer">Dry run preview (do not push to remote)</label>
          </div>

          <div class="pt-2">
            <button class="btn btn-primary" id="pr-btn" onclick="runPR()">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><line x1="6" y1="9" x2="6" y2="21"/></svg>
              Execute PR Workflow
            </button>
          </div>
        </div>
      </div>

      ${pr ? `
        <div class="card p-6 border-neutral-200 bg-neutral-50/50">
          <div class="flex items-center justify-between mb-3">
            <span class="font-bold text-[14px] text-black">PR Workflow Record</span>
            <span class="badge" style="background:#000000;color:#FFFFFF;border:1px solid #000;">Dry Run / Audited</span>
          </div>
          <div class="space-y-1 font-mono text-[12px] text-neutral-800">
            <div>Branch: <strong>${pr.branch || 'opentrace/migration-patch'}</strong></div>
            <div>Commits: <strong>${pr.commit_hash || 'local-preview'}</strong></div>
          </div>
        </div>` : ''}
    </div>`;
}

async function runPR() {
  const btn = document.getElementById('pr-btn');
  const token = document.getElementById('pr-token')?.value.trim();
  const base = document.getElementById('pr-base')?.value.trim() || 'main';
  const dryRun = document.getElementById('pr-dryrun')?.checked ?? true;

  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Processing PR…';
  }

  try {
    const res = await API.post('/api/pr', {
      base_branch: base,
      github_token: token || null,
      dry_run: dryRun,
    });
    toast(dryRun ? 'Dry run completed successfully' : 'Pull request opened!', 'success');
    await loadWorkspace();
  } catch (e) {
    toast('PR failed: ' + e.message, 'error');
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Execute PR Workflow';
    }
  }
}

// ── 6. Workflow Guide (Dedicated Step-by-Step Onboarding) ─────────────────────
function renderGuide(ws) {
  return `
    <div class="max-w-4xl mx-auto space-y-6">

      <!-- Introduction Banner -->
      <div class="card p-6 bg-black text-white border-black">
        <div class="flex items-center justify-between mb-2">
          <span class="badge" style="background:#27272A;color:#FFFFFF;border:1px solid #3F3F46;">Architecture Guide</span>
          <span class="text-[12px] text-neutral-400 font-mono">End-to-End Migration Flow</span>
        </div>
        <h2 class="text-xl font-bold tracking-tight text-white mb-2">How OpenTrace Automates API Change Migration</h2>
        <p class="text-[13px] text-neutral-300 max-w-2xl leading-relaxed">
          OpenTrace closes the gap between upstream API contract modifications and downstream consuming repositories.
          Run it locally in your CLI or orchestrate it via this web dashboard.
        </p>
      </div>

      <!-- Step 1: Install & Sync CLI -->
      <div class="card p-6">
        <div class="flex items-center gap-3 mb-3">
          <div class="w-8 h-8 rounded-lg bg-black text-white flex items-center justify-center font-bold text-[13px]">1</div>
          <div>
            <div class="font-bold text-[15px] text-black">Install & Sync OpenTrace CLI from GitHub</div>
            <div class="text-[12px] text-neutral-400">Run migrations directly in terminal or CI/CD pipelines</div>
          </div>
        </div>
        <p class="text-[13px] text-neutral-600 mb-3 leading-relaxed">
          <strong>Why CLI?</strong> The CLI runs at native speed, executes directly against local git trees, and ensures full privacy because no proprietary source code leaves your machine.
        </p>
        <div class="space-y-2">
          <div class="bg-neutral-900 text-neutral-200 p-3 rounded-xl font-mono text-[12px] flex items-center justify-between">
            <span>git clone https://github.com/Jithendra-coder/OpenTrace.git && cd OpenTrace</span>
            <button class="text-neutral-400 hover:text-white text-[11px]" onclick="App.copyToClipboard('git clone https://github.com/Jithendra-coder/OpenTrace.git && cd OpenTrace')">Copy</button>
          </div>
          <div class="bg-neutral-900 text-neutral-200 p-3 rounded-xl font-mono text-[12px] flex items-center justify-between">
            <span>pip install -e .</span>
            <button class="text-neutral-400 hover:text-white text-[11px]" onclick="App.copyToClipboard('pip install -e .')">Copy</button>
          </div>
        </div>
        <div class="mt-3 flex items-center gap-2">
          <button class="btn btn-secondary text-[12px]" onclick="App.openCliModal()">Open CLI Installation Window</button>
        </div>
      </div>

      <!-- Step 2: Analyze API Breaking Changes -->
      <div class="card p-6">
        <div class="flex items-center gap-3 mb-3">
          <div class="w-8 h-8 rounded-lg bg-black text-white flex items-center justify-center font-bold text-[13px]">2</div>
          <div>
            <div class="font-bold text-[15px] text-black">Analyze Contract Diffs & Call Graph</div>
            <div class="text-[12px] text-neutral-400">OpenAPI 3.0 semantic comparison + AST blast radius</div>
          </div>
        </div>
        <p class="text-[13px] text-neutral-600 mb-3 leading-relaxed">
          OpenTrace computes the exact semantic differences between OpenAPI specifications (e.g. parameter removals, schema alterations, renamed endpoints) and searches your repository using Python AST parsing to locate direct call sites and indirect upstream callers.
        </p>
        <div class="bg-neutral-900 text-neutral-200 p-3.5 rounded-xl font-mono text-[12px] flex items-center justify-between">
          <span>opentrace analyze --old sample1/api_v1.yaml --new sample1/api_v2.yaml --repo sample1</span>
          <button class="text-neutral-400 hover:text-white text-[11px]" onclick="App.copyToClipboard('opentrace analyze --old sample1/api_v1.yaml --new sample1/api_v2.yaml --repo sample1')">Copy</button>
        </div>
      </div>

      <!-- Step 3: RouteForge Repair Planning -->
      <div class="card p-6">
        <div class="flex items-center gap-3 mb-3">
          <div class="w-8 h-8 rounded-lg bg-black text-white flex items-center justify-center font-bold text-[13px]">3</div>
          <div>
            <div class="font-bold text-[15px] text-black">Generate Patches with RouteForge</div>
            <div class="text-[12px] text-neutral-400">Deterministic code replacement & bounded repairs</div>
          </div>
        </div>
        <p class="text-[13px] text-neutral-600 mb-3 leading-relaxed">
          RouteForge evaluates the risk of each change and generates precise code edits without hallucinations:
        </p>
        <ul class="text-[12.5px] text-neutral-600 space-y-1.5 list-disc list-inside mb-3">
          <li><strong>Economy:</strong> Fast deterministic AST rewrites for predictable contract renames.</li>
          <li><strong>Balanced:</strong> Bounded candidate synthesis with AST validation.</li>
          <li><strong>Comprehensive:</strong> Deep multi-file propagation.</li>
        </ul>
        <div class="bg-neutral-900 text-neutral-200 p-3.5 rounded-xl font-mono text-[12px] flex items-center justify-between">
          <span>opentrace migrate --policy balanced</span>
          <button class="text-neutral-400 hover:text-white text-[11px]" onclick="App.copyToClipboard('opentrace migrate --policy balanced')">Copy</button>
        </div>
      </div>

      <!-- Step 4: Ephemeral Sandbox Validation -->
      <div class="card p-6">
        <div class="flex items-center gap-3 mb-3">
          <div class="w-8 h-8 rounded-lg bg-black text-white flex items-center justify-center font-bold text-[13px]">4</div>
          <div>
            <div class="font-bold text-[15px] text-black">Validate in Ephemeral Sandbox</div>
            <div class="text-[12px] text-neutral-400">Zero-risk validation in isolated temporary files</div>
          </div>
        </div>
        <p class="text-[13px] text-neutral-600 mb-3 leading-relaxed">
          Before altering any source file, OpenTrace clones the affected files into a temporary directory, applies the patch, verifies AST syntax, and runs unit tests. If any test fails, the patch is rejected and your code remains unmodified.
        </p>
        <div class="bg-neutral-900 text-neutral-200 p-3.5 rounded-xl font-mono text-[12px] flex items-center justify-between">
          <span>opentrace validate</span>
          <button class="text-neutral-400 hover:text-white text-[11px]" onclick="App.copyToClipboard('opentrace validate')">Copy</button>
        </div>
      </div>

      <!-- Step 5: Safe Application & GitHub PR -->
      <div class="card p-6">
        <div class="flex items-center gap-3 mb-3">
          <div class="w-8 h-8 rounded-lg bg-black text-white flex items-center justify-center font-bold text-[13px]">5</div>
          <div>
            <div class="font-bold text-[15px] text-black">Apply Changes or Open GitHub PR</div>
            <div class="text-[12px] text-neutral-400">Full audit logging & team code review</div>
          </div>
        </div>
        <p class="text-[13px] text-neutral-600 mb-3 leading-relaxed">
          Once verified, commit the changes directly with confirmation or open a draft PR complete with an audit manifest:
        </p>
        <div class="bg-neutral-900 text-neutral-200 p-3.5 rounded-xl font-mono text-[12px] flex items-center justify-between">
          <span>opentrace apply  # Or: opentrace pr --base main</span>
          <button class="text-neutral-400 hover:text-white text-[11px]" onclick="App.copyToClipboard('opentrace apply')">Copy</button>
        </div>
      </div>

    </div>`;
}

// ── 7. Audit & Decision Log ───────────────────────────────────────────────────
function renderFeedback(ws) {
  const records = ws?.feedback || [];
  const actionColors = { ACCEPTED: 'green', REJECTED: 'red', SKIPPED: 'gray', DEFERRED: 'amber' };

  return `
    <div class="max-w-4xl mx-auto space-y-6">
      <div class="card p-6">
        <div class="flex items-center justify-between mb-3">
          <div>
            <div class="text-[15px] font-bold text-black">Migration Audit Trail</div>
            <div class="text-[12px] text-neutral-400 mt-0.5">Permanent compliance log of patch applications, reviews, and decisions</div>
          </div>
          <button class="btn btn-secondary text-[12px]" onclick="App.exportReport()">Export Full Report</button>
        </div>
        ${C.banner('Audit records document all automated and human interventions. They provide verifiable evidence for security compliance and engineering governance.', 'info')}
      </div>

      <div class="card overflow-hidden">
        <div class="px-6 pt-5 pb-3 flex items-center justify-between border-b border-neutral-100">
          <div class="text-[14px] font-bold text-black">Recorded Decisions (${records.length})</div>
          <span class="text-[12px] text-neutral-400">Append-only audit log</span>
        </div>

        ${records.length === 0 ? `
          <div class="p-8 text-center">
            <div class="text-[13px] text-neutral-500 mb-1">No migration actions recorded yet.</div>
            <div class="text-[11.5px] text-neutral-400">Decisions are logged automatically when you accept, apply, or reject patches.</div>
          </div>
        ` : `
          <table>
            <thead><tr>
              <th>Timestamp</th><th>Patch Hash</th><th>Strategy</th><th>Validation</th><th>Decision</th>
            </tr></thead>
            <tbody>
              ${records.map(r => `
                <tr>
                  <td class="font-mono text-[11.5px] text-neutral-500">${r.timestamp_utc?.slice(0,16).replace('T',' ') || '—'}</td>
                  <td class="font-mono text-[11.5px] text-black font-semibold">${(r.patch_id || '').slice(0, 16)}…</td>
                  <td>${r.selected_strategy ? C.badge(r.selected_strategy, 'slate') : '—'}</td>
                  <td>${r.validation_status ? C.statusBadge(r.validation_status) : '—'}</td>
                  <td>${C.badge(r.user_action || 'RECORDED', actionColors[r.user_action] || 'gray')}</td>
                </tr>
                ${r.rejection_reason ? `<tr style="background:#FFF8F8;"><td colspan="5" class="px-5 pb-2.5 text-[12px] text-red-600">Reason: ${r.rejection_reason}</td></tr>` : ''}
              `).join('')}
            </tbody>
          </table>
        `}
      </div>
    </div>`;
}

// ── 8. Settings ───────────────────────────────────────────────────────────────
function renderSettings(ws) {
  const activeProj = State.projects.find(p => p.id === State.activeProjectId) || {
    name: 'Default Workspace',
    repo_path: ws?.workspace || '—',
  };

  return `
    <div class="max-w-3xl mx-auto space-y-6">

      <!-- Active Workspace Information -->
      <div class="card p-6">
        ${C.sectionHead('Workspace Information', 'Active repository metadata and .opentrace/ storage configuration')}
        <div class="space-y-3">
          <div class="flex items-center justify-between py-2 border-b border-neutral-100">
            <span class="text-[13px] font-medium text-neutral-600">Active Project Name</span>
            <span class="font-bold text-[13px] text-black">${activeProj.name}</span>
          </div>
          <div class="flex items-center justify-between py-2 border-b border-neutral-100">
            <span class="text-[13px] font-medium text-neutral-600">Repository Directory</span>
            <span class="font-mono text-[12px] text-neutral-800 truncate max-w-sm" title="${activeProj.repo_path}">${activeProj.repo_path}</span>
          </div>
          <div class="flex items-center justify-between py-2 border-b border-neutral-100">
            <span class="text-[13px] font-medium text-neutral-600">Metadata Storage</span>
            <span class="font-mono text-[12px] text-emerald-700 font-medium">.opentrace/ (Ready)</span>
          </div>
        </div>
        <div class="mt-4 flex items-center gap-2">
          <button class="btn btn-secondary text-[12px]" onclick="App.openManageProjectsModal()">Manage Workspaces</button>
          <button class="btn btn-secondary text-[12px]" onclick="App.openAddProjectModal()">+ Add Workspace</button>
        </div>
      </div>

      <!-- CLI & Runtime Environment -->
      <div class="card p-6">
        ${C.sectionHead('Runtime & CLI Health', 'OpenTrace command-line tools configuration')}
        <div class="text-[13px] text-neutral-600 mb-4 leading-relaxed">
          OpenTrace CLI can be executed as <code class="font-mono text-black font-semibold">opentrace</code> or via <code class="font-mono text-black font-semibold">python -m opentrace</code> across all local Python environments.
        </div>
        <div class="flex items-center gap-3">
          <button class="btn btn-primary text-[12px]" onclick="App.openCliModal()">Open CLI Setup Guide</button>
          <button class="btn btn-secondary text-[12px]" onclick="App.copyToClipboard('pip install -e .')">Copy pip install -e .</button>
        </div>
      </div>

      <!-- Engine & Safety Parameters -->
      <div class="card p-6">
        ${C.sectionHead('Safety & Execution Engine', 'Policies governing AST validation and sandbox isolation')}
        <div class="space-y-3 text-[13px]">
          <div class="flex items-center justify-between py-2 border-b border-neutral-100">
            <div>
              <div class="font-medium text-black">AST Strict Mode</div>
              <div class="text-[11.5px] text-neutral-400">Verifies Python AST parseability before any file is saved</div>
            </div>
            <span class="badge badge-green">Always Enabled</span>
          </div>
          <div class="flex items-center justify-between py-2 border-b border-neutral-100">
            <div>
              <div class="font-medium text-black">Ephemeral Sandbox Isolation</div>
              <div class="text-[11.5px] text-neutral-400">Runs candidate diffs and unit tests in temporary folders</div>
            </div>
            <span class="badge badge-green">Always Enabled</span>
          </div>
        </div>
      </div>

      <!-- Danger Zone -->
      <div class="card p-6 border-red-200">
        <div class="flex items-center justify-between">
          <div>
            <div class="text-[14px] font-bold text-red-700">Clear Workspace Cache</div>
            <div class="text-[12px] text-neutral-500 mt-0.5">Delete all cached analysis, migration plans, and validation results in .opentrace/ to start fresh.</div>
          </div>
          <button class="btn btn-danger text-[13px]" onclick="App.resetWorkspace()">
            Clear Cache
          </button>
        </div>
      </div>

    </div>`;
}

// ── 9. Interactive API Simulator ──────────────────────────────────────────────
const SimState = {
  selectedApi: 'payments',
  isChanged: false,
  analyzed: false,
  apis: {
    payments: {
      name: 'Payments Microservice',
      endpoint: 'POST /payments',
      method: 'POST',
      path: '/payments',
      desc: 'Handles customer credit card & invoice payments',
      originalSchema: '{\n  "amount": 49.99,\n  "currency": "USD",\n  "customer_id": "cust_123"\n}',
      changedSchema: '{\n  "price_cents": 4999, // BREAKING: "amount" removed\n  "currency": "USD",\n  "customer_id": "cust_123"\n}',
      changeType: 'request_property_removed',
      field: 'amount',
      directImpacts: [
        { file: 'payment_service.py', line: 7, symbol: 'create_payment' }
      ],
      indirectSymbols: [
        { file: 'checkout.py', symbol: 'process_checkout', distance: 1 },
        { file: 'orders.py', symbol: 'charge_order', distance: 2 }
      ],
      patchDiff: {
        del: '- "amount": amount,',
        add: '+ "price_cents": int(amount * 100),'
      }
    },
    users: {
      name: 'User Profile Service',
      endpoint: 'GET /users/{id}',
      method: 'GET',
      path: '/users/{id}',
      desc: 'Fetches user details and permission roles',
      originalSchema: '{\n  "id": 1042 // integer\n}',
      changedSchema: '{\n  "id": "usr_9f83a-4b21-482a" // BREAKING: type changed to UUID string\n}',
      changeType: 'path_parameter_type_changed',
      field: 'id',
      directImpacts: [
        { file: 'auth_client.py', line: 14, symbol: 'get_user_profile' }
      ],
      indirectSymbols: [
        { file: 'session_manager.py', symbol: 'validate_session', distance: 1 }
      ],
      patchDiff: {
        del: '- user_id = int(request.user_id)',
        add: '+ user_id = str(request.user_id) # UUID compatible'
      }
    },
    orders: {
      name: 'Order Management API',
      endpoint: 'POST /orders/checkout',
      method: 'POST',
      path: '/orders/checkout',
      desc: 'Processes shopping cart items and initiates fulfillment',
      originalSchema: '{\n  "items": [...],\n  "payment_method": "credit_card"\n}',
      changedSchema: '{\n  "items": [...],\n  "billing_address": { "zip": "10001" } // BREAKING: payment_method removed\n}',
      changeType: 'request_property_removed',
      field: 'payment_method',
      directImpacts: [
        { file: 'checkout_service.py', line: 22, symbol: 'submit_order' }
      ],
      indirectSymbols: [
        { file: 'cart.py', symbol: 'flush_cart', distance: 1 }
      ],
      patchDiff: {
        del: '- "payment_method": cart.payment_method,',
        add: '+ "billing_address": cart.billing_address,'
      }
    }
  }
};

function renderPlayground(ws) {
  const current = SimState.apis[SimState.selectedApi] || SimState.apis.payments;
  const isChanged = SimState.isChanged;
  const isAnalyzed = SimState.analyzed;

  return `
    <div class="max-w-4xl mx-auto space-y-6">
      <!-- Step 1: Select API -->
      <div class="card p-6">
        <div class="flex items-center justify-between mb-4">
          <div>
            <div class="text-[15px] font-bold text-black">1. Select an API Endpoint to Test</div>
            <div class="text-[12.5px] text-neutral-500 mt-0.5">Click any microservice API to simulate a contract breaking change</div>
          </div>
          <button class="btn btn-secondary text-[12px]" onclick="App.resetSim()">Reset Simulator</button>
        </div>

        <div class="grid grid-cols-3 gap-4">
          ${Object.entries(SimState.apis).map(([k, api]) => `
            <div class="sim-api-card p-4 rounded-xl ${SimState.selectedApi === k ? 'active' : 'bg-white'}" onclick="App.selectSimApi('${k}')">
              <div class="flex items-center justify-between mb-2">
                ${C.methodBadge(api.method)}
                <span class="text-[10px] font-bold text-neutral-400 uppercase font-mono">${k}</span>
              </div>
              <div class="font-bold text-[13.5px] text-black truncate">${api.name}</div>
              <div class="font-mono text-[11.5px] text-neutral-500 mt-0.5">${api.endpoint}</div>
              <div class="text-[11px] text-neutral-400 mt-2 line-clamp-2">${api.desc}</div>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- Step 2: Mutate Contract -->
      <div class="card p-6">
        <div class="flex items-center justify-between mb-4">
          <div>
            <div class="text-[15px] font-bold text-black">2. Mutate API Contract (Simulate Breaking Change)</div>
            <div class="text-[12.5px] text-neutral-500 mt-0.5">Simulate removing a required parameter or changing data types</div>
          </div>
          <button class="btn ${isChanged ? 'btn-secondary text-amber-700 bg-amber-50 border-amber-200' : 'btn-primary'}" onclick="App.mutateSimApi()">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            ${isChanged ? 'Revert to Original API' : 'Simulate Breaking Change'}
          </button>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <div class="text-[12px] font-bold text-neutral-500 mb-1.5 flex items-center justify-between">
              <span>Original API Contract (v1)</span>
              <span class="badge badge-green text-[10px]">Active</span>
            </div>
            <pre class="bg-neutral-900 text-neutral-300 font-mono text-[11.5px] p-4 rounded-xl overflow-x-auto leading-relaxed border border-neutral-800">${C._esc(current.originalSchema)}</pre>
          </div>
          <div>
            <div class="text-[12px] font-bold text-neutral-500 mb-1.5 flex items-center justify-between">
              <span>Simulated New API (v2)</span>
              ${isChanged ? `<span class="badge badge-red text-[10px] node-pulse">BREAKING CHANGE</span>` : `<span class="badge badge-gray text-[10px]">Unmodified</span>`}
            </div>
            <pre class="${isChanged ? 'bg-neutral-950 border border-neutral-700 text-amber-200' : 'bg-neutral-950 border border-neutral-800 text-neutral-300'} font-mono text-[11.5px] p-4 rounded-xl overflow-x-auto leading-relaxed transition-all">${C._esc(isChanged ? current.changedSchema : current.originalSchema)}</pre>
          </div>
        </div>

        ${isChanged ? `
          <div class="mt-5 pt-4 border-t border-neutral-100 flex items-center justify-between">
            <div class="text-[13px] text-amber-800 font-medium flex items-center gap-2">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#D97706" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>
              Breaking change ready to simulate. Click below to analyze full ripple impact.
            </div>
            <button class="btn btn-primary" onclick="App.analyzeSimImpact()">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              Analyze Impact & Trace Call Graph
            </button>
          </div>
        ` : ''}
      </div>

      <!-- Step 3: Simulation Results -->
      ${isAnalyzed ? `
        <div class="space-y-5 animate-slide-up">
          ${C.visualCallGraph(current.directImpacts, current.indirectSymbols, [{ method: current.method, path: current.path, field: current.field }])}

          <div class="grid grid-cols-2 gap-4">
            <div class="card p-5">
              <div class="text-[14px] font-bold text-black mb-3 flex items-center justify-between">
                <span>Detected Breaking Changes</span>
                <span class="badge badge-red text-[11px]">1 Critical</span>
              </div>
              <table>
                <thead><tr><th>Method</th><th>Endpoint</th><th>Type</th><th>Field</th></tr></thead>
                <tbody>
                  <tr>
                    <td>${C.methodBadge(current.method)}</td>
                    <td class="font-mono text-[12px]">${current.path}</td>
                    <td>${C.badge('BREAKING', 'red')}</td>
                    <td class="font-mono text-[12px] text-neutral-500">${current.field}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div class="card p-5">
              <div class="text-[14px] font-bold text-black mb-3 flex items-center justify-between">
                <span>Auto-Generated Migration Patch</span>
                <span class="badge badge-green text-[11px]">RouteForge SMALL</span>
              </div>
              <div class="text-[12px] text-neutral-500 mb-2">Target file: <code class="font-mono text-black font-semibold">${current.directImpacts[0]?.file}</code></div>
              <div class="rounded-lg overflow-hidden border border-neutral-200 font-mono text-[12px]">
                <div class="diff-line-del px-3 py-1.5">${C._esc(current.patchDiff.del)}</div>
                <div class="diff-line-add px-3 py-1.5">${C._esc(current.patchDiff.add)}</div>
              </div>
            </div>
          </div>
        </div>
      ` : ''}
    </div>`;
}

// ── App Actions ───────────────────────────────────────────────────────────────
const App = {
  refresh: loadWorkspace,

  closeAllModals: function() {
    App.closeCliModal();
    App.closeAddProjectModal();
    App.closeManageProjectsModal();
  },

  handlePolicy: function(input) {
    document.querySelectorAll('.policy-option').forEach(el => {
      const radio = el.querySelector('input[type="radio"]');
      if (radio && radio.checked) {
        el.style.borderColor = '#000000';
        el.style.backgroundColor = '#F4F4F5';
      } else {
        el.style.borderColor = '#E4E4E7';
        el.style.backgroundColor = '#FFFFFF';
      }
    });
  },

  setAnalyzePreset: function(presetKey) {
    const presets = {
      sample1: {
        old: 'sample1/api_v1.yaml',
        new: 'sample1/api_v2.yaml',
        repo: 'sample1',
      },
      sample2: {
        old: 'sample2/api_v1.yaml',
        new: 'sample2/api_v2.yaml',
        repo: 'sample2',
      },
      demo: {
        old: 'demo/payment_api_v1.yaml',
        new: 'demo/payment_api_v2.yaml',
        repo: 'demo/ecommerce',
      },
    };
    const p = presets[presetKey];
    if (!p) return;
    const o = document.getElementById('a-old');
    const n = document.getElementById('a-new');
    const r = document.getElementById('a-repo');
    if (o) o.value = p.old;
    if (n) n.value = p.new;
    if (r) r.value = p.repo;
  },

  runPreset: async function(presetKey) {
    App.setAnalyzePreset(presetKey);
    navigate('analyze');
    setTimeout(() => {
      runAnalyze();
    }, 80);
  },

  copyCurrentCliCommand: function() {
    const oldPath = document.getElementById('a-old')?.value.trim() || 'sample1/api_v1.yaml';
    const newPath = document.getElementById('a-new')?.value.trim() || 'sample1/api_v2.yaml';
    const repoPath = document.getElementById('a-repo')?.value.trim() || 'sample1';
    const cmd = `opentrace analyze --old ${oldPath} --new ${newPath} --repo ${repoPath}`;
    App.copyToClipboard(cmd);
  },

  resetWorkspace: async function() {
    if (!confirm('Are you sure you want to reset the workspace? This will delete all .opentrace/ cached analysis and plans.')) {
      return;
    }
    try {
      await API.post('/api/reset', {});
      toast('Workspace reset successfully', 'success');
      await loadWorkspace();
    } catch (e) {
      toast('Reset failed: ' + e.message, 'error');
    }
  },

  applyPatch: async function() {
    if (!confirm('Apply validated migration patch to repository files? This will directly update target files.')) {
      return;
    }
    try {
      const res = await API.post('/api/apply', {});
      toast('Patch successfully applied to codebase', 'success');
      await loadWorkspace();
    } catch (e) {
      toast('Apply failed: ' + e.message, 'error');
    }
  },

  // ── Project Management Modals ──
  openManageProjectsModal: async function() {
    const modal = document.getElementById('manage-projects-modal');
    if (modal) {
      modal.classList.remove('hidden');
      modal.classList.add('flex');
    }
    await App.loadManageProjectsList();
  },

  closeManageProjectsModal: function() {
    const modal = document.getElementById('manage-projects-modal');
    if (modal) {
      modal.classList.remove('flex');
      modal.classList.add('hidden');
    }
  },

  loadManageProjectsList: async function() {
    const container = document.getElementById('modal-project-list');
    if (!container) return;
    try {
      const data = await API.get('/api/projects');
      const projects = data.projects || [];
      const activeId = data.active_id;

      if (projects.length === 0) {
        container.innerHTML = `<div class="text-neutral-400 text-[13px] text-center py-4">No registered projects.</div>`;
        return;
      }

      container.innerHTML = projects.map(p => `
        <div class="flex items-center justify-between p-3 rounded-xl border border-neutral-200 bg-neutral-50/50">
          <div class="min-w-0 pr-3">
            <div class="flex items-center gap-2">
              <span class="font-bold text-[13.5px] text-black truncate">${p.name}</span>
              ${p.id === activeId ? '<span class="badge badge-green text-[10px]">Active</span>' : ''}
            </div>
            <div class="font-mono text-[11px] text-neutral-500 truncate mt-0.5">${p.repo_path}</div>
          </div>
          <div class="flex items-center gap-2 flex-shrink-0">
            ${p.id !== activeId ? `
              <button class="btn btn-secondary text-[11.5px] py-1 px-2.5" onclick="App.switchProject('${p.id}')">Switch</button>
            ` : ''}
            <button class="text-neutral-400 hover:text-red-600 hover:bg-red-50 p-1.5 rounded-lg transition-all" title="Remove project" onclick="App.deleteProject('${p.id}', '${p.name}')">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
          </div>
        </div>
      `).join('');
    } catch (e) {
      container.innerHTML = `<div class="text-red-500 text-[12px]">Failed to load projects: ${e.message}</div>`;
    }
  },

  deleteProject: async function(projectId, name) {
    if (!confirm(`Are you sure you want to delete project '${name}'?`)) return;
    try {
      await API.delete(`/api/projects/${projectId}`);
      toast(`Project '${name}' removed`, 'success');
      await App.loadManageProjectsList();
      await loadWorkspace();
    } catch (e) {
      toast('Failed to remove project: ' + e.message, 'error');
    }
  },

  openAddProjectModal: function() {
    const modal = document.getElementById('add-project-modal');
    if (modal) {
      modal.classList.remove('hidden');
      modal.classList.add('flex');
    }
  },

  closeAddProjectModal: function() {
    const modal = document.getElementById('add-project-modal');
    if (modal) {
      modal.classList.remove('flex');
      modal.classList.add('hidden');
    }
  },

  handleRepoBrowse: function(input) {
    if (input.files && input.files.length > 0) {
      const file = input.files[0];
      const relPath = file.webkitRelativePath || '';
      const folderName = relPath.split('/')[0] || file.name;
      const repoInput = document.getElementById('new-proj-repo');
      const nameInput = document.getElementById('new-proj-name');
      if (repoInput) repoInput.value = folderName;
      if (nameInput && !nameInput.value) nameInput.value = folderName;
    }
  },

  handleSpecBrowse: function(input) {
    if (input.files && input.files.length > 0) {
      const file = input.files[0];
      const specInput = document.getElementById('new-proj-spec');
      if (specInput) specInput.value = file.name;
    }
  },

  submitAddProject: async function() {
    const name = document.getElementById('new-proj-name')?.value.trim();
    const repo = document.getElementById('new-proj-repo')?.value.trim();
    const spec = document.getElementById('new-proj-spec')?.value.trim();

    if (!repo) {
      toast('Repository Directory Path is required', 'error');
      return;
    }

    try {
      const res = await API.post('/api/projects', {
        name: name || repo.split(/[\/\\]/).pop(),
        repo_path: repo,
        spec_path: spec || null,
      });
      toast(`Project '${res.project.name}' added & activated`, 'success');
      App.closeAddProjectModal();
      const n = document.getElementById('new-proj-name');
      const r = document.getElementById('new-proj-repo');
      const s = document.getElementById('new-proj-spec');
      if (n) n.value = '';
      if (r) r.value = '';
      if (s) s.value = '';
      await loadWorkspace();
    } catch (e) {
      toast('Failed to add project: ' + e.message, 'error');
    }
  },

  switchProject: async function(projectId) {
    if (!projectId) return;
    try {
      await API.post('/api/projects/switch', { project_id: projectId });
      await App.loadManageProjectsList();
      await loadWorkspace();
    } catch (e) {
      toast('Failed to switch project: ' + e.message, 'error');
    }
  },

  exportReport: function() {
    window.location.href = '/api/export-report';
  },

  // ── Simulator Controls ──
  selectSimApi: function(key) {
    if (!SimState.apis[key]) return;
    SimState.selectedApi = key;
    SimState.isChanged = false;
    SimState.analyzed = false;
    navigate('playground');
  },

  mutateSimApi: function() {
    SimState.isChanged = !SimState.isChanged;
    SimState.analyzed = false;
    navigate('playground');
  },

  analyzeSimImpact: function() {
    SimState.analyzed = true;
    navigate('playground');
  },

  resetSim: function() {
    SimState.selectedApi = 'payments';
    SimState.isChanged = false;
    SimState.analyzed = false;
    navigate('playground');
  },

  handleAnalyzeBrowse: function(input, targetId) {
    if (input.files && input.files.length > 0) {
      const file = input.files[0];
      const target = document.getElementById(targetId);
      if (target) {
        target.value = file.name;
      }
    }
  },

  handleAnalyzeRepoBrowse: function(input) {
    if (input.files && input.files.length > 0) {
      const file = input.files[0];
      const relPath = file.webkitRelativePath || '';
      const folderName = relPath.split('/')[0] || file.name;
      const target = document.getElementById('a-repo');
      if (target) {
        target.value = folderName;
      }
    }
  },

  openCliModal: async function() {
    const modal = document.getElementById('cli-modal');
    if (modal) {
      modal.classList.remove('hidden');
      modal.classList.add('flex');
    }
    try {
      const data = await API.get('/api/cli-status');
      const badge = document.getElementById('cli-status-badge');
      const envList = data.environments || [];
      const envHtml = envList.length > 0 ? `
        <div class="mt-2.5 pt-2 border-t border-neutral-200 space-y-1.5 text-[11px]">
          <div class="font-semibold text-neutral-800">Detected Python Environments (${data.installed_count || 0} of ${data.total_environments || envList.length} ready):</div>
          ${envList.map(e => `
            <div class="flex items-center justify-between font-mono bg-white px-2.5 py-1 rounded border border-neutral-200">
              <span class="truncate max-w-[280px]" title="${e.executable}">${e.version || e.executable}</span>
              ${e.installed ? '<span class="text-emerald-700 font-sans font-medium flex items-center gap-1">✓ Ready</span>' : '<span class="text-amber-700 font-sans font-medium">Pending</span>'}
            </div>
          `).join('')}
        </div>
      ` : '';

      if (badge) {
        if (data.installed) {
          badge.className = 'p-3.5 bg-neutral-50 rounded-xl border border-neutral-200 text-neutral-800 text-[12px]';
          badge.innerHTML = `
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
              <span class="font-bold text-black">OpenTrace CLI is Installed & Configured</span>
            </div>
            ${envHtml}
          `;
        } else {
          badge.className = 'p-3.5 bg-neutral-50 rounded-xl border border-neutral-200 text-neutral-800 text-[12px]';
          badge.innerHTML = `
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full bg-amber-500"></span>
              <span class="font-bold text-black">CLI not registered on system PATH yet.</span>
            </div>
            ${envHtml}
          `;
        }
      }
    } catch (e) {
      console.warn('CLI status fetch error:', e);
    }
  },

  runAutoInstall: async function() {
    const btn = document.getElementById('btn-auto-install');
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = `<svg class="animate-spin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10"/></svg> Syncing…`;
    }
    toast('Configuring OpenTrace CLI across Python environments…', 'info');
    try {
      const res = await API.post('/api/install-cli');
      if (res.success) {
        toast('CLI successfully configured', 'success');
        await App.openCliModal();
      } else {
        toast('Configuration note: ' + (res.message || 'Check logs'), 'info');
      }
    } catch (e) {
      toast('Auto-sync failed: ' + e.message, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Sync All`;
      }
    }
  },

  closeCliModal: function() {
    const modal = document.getElementById('cli-modal');
    if (modal) {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
    }
  },

  copyToClipboard: function(text) {
    navigator.clipboard.writeText(text);
    toast(`Copied '${text}' to clipboard`, 'success');
  }
};

// ── Global Event Listeners ────────────────────────────────────────────────────
document.getElementById('sidebar-nav')?.addEventListener('click', e => {
  const item = e.target.closest('.nav-item');
  if (item?.dataset.page) navigate(item.dataset.page);
});

window.addEventListener('hashchange', () => {
  const page = window.location.hash.replace('#', '').trim();
  if (PAGES[page] && State.page !== page) {
    navigate(page, false);
  }
});

window.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    App.closeAllModals();
  }
});

// Initialize workspace load on startup
State.page = getInitialPage();
loadWorkspace();
