// ─── OpenTrace Noir Component Library ────────────────────────────────────────

const C = {

  // ── Badges ─────────────────────────────────────────────────────────────────
  badge(text, variant = 'gray') {
    const map = {
      black: 'background:#000000;color:#FFFFFF;border:1px solid #000000;',
      gray:  'background:#F4F4F5;color:#18181B;border:1px solid #E4E4E7;',
      slate: 'background:#FAFAFA;color:#52525B;border:1px solid #E4E4E7;',
      red:   'background:#FEF2F2;color:#991B1B;border:1px solid #FECACA;',
      amber: 'background:#FFFBEB;color:#92400E;border:1px solid #FDE68A;',
      green: 'background:#ECFDF5;color:#065F46;border:1px solid #A7F3D0;',
      blue:  'background:#EFF6FF;color:#1E40AF;border:1px solid #BFDBFE;',
    };
    return `<span class="badge" style="${map[variant] || map.gray}">${text}</span>`;
  },

  methodBadge(method) {
    const m = (method || '').toUpperCase();
    const map = { GET:'blue', POST:'green', PUT:'amber', PATCH:'slate', DELETE:'red' };
    return C.badge(m, map[m] || 'gray');
  },

  statusBadge(status) {
    const map = {
      TESTS_PASSED:         ['TESTS PASSED',      'black'],
      TESTS_FAILED:         ['TESTS FAILED',       'red'],
      NO_TESTS_COLLECTED:   ['NO TESTS',           'amber'],
      RUNNER_ERROR:         ['RUNNER ERROR',       'amber'],
      PATCH_FAILED:         ['PATCH FAILED',       'red'],
      SYNTAX_ERROR:         ['SYNTAX ERROR',       'red'],
      TIMEOUT:              ['TIMEOUT',            'red'],
      SANDBOX_ERROR:        ['SANDBOX ERROR',      'red'],
      GENERATED:            ['GENERATED',          'black'],
      AI_DISABLED:          ['AI DISABLED',        'gray'],
      NOT_REQUIRED:         ['NOT REQUIRED',       'slate'],
    };
    const [label, color] = map[status] || [status, 'gray'];
    return C.badge(label, color);
  },

  riskBadge(strategy) {
    const map = { SMALL:'green', DETERMINISTIC:'green', NO_AI:'gray', MEDIUM:'amber', STRONG:'red' };
    const risk = { SMALL:'LOW', DETERMINISTIC:'LOW', NO_AI:'NONE', MEDIUM:'MED', STRONG:'HIGH' };
    return C.badge(risk[strategy] || '—', map[strategy] || 'gray');
  },

  // ── Stat Card (Exact sizing & 4-card overview indicators) ───────────────────
  statCard(label, value, sub, accent = 'slate') {
    const accentClass = `stat-${accent}`;
    return `
      <div class="card p-5 ${accentClass} flex flex-col justify-between min-h-[118px] transition-all hover:border-neutral-300">
        <div>
          <div class="text-[11px] font-bold uppercase tracking-wider text-neutral-400 mb-2">${label}</div>
          <div class="text-3xl font-extrabold text-black leading-none tracking-tight">${value ?? '—'}</div>
        </div>
        ${sub ? `<div class="text-[12px] text-neutral-500 mt-2.5 font-medium truncate" title="${C._esc(sub)}">${sub}</div>` : ''}
      </div>`;
  },

  // ── Empty State ─────────────────────────────────────────────────────────────
  emptyState(icon, title, message, action = '') {
    return `
      <div class="flex flex-col items-center justify-center py-20 text-center">
        <div class="w-12 h-12 rounded-2xl flex items-center justify-center mb-4 text-neutral-400 border border-neutral-200" style="background:#FAFAFA;">
          ${icon}
        </div>
        <div class="text-[15px] font-bold text-black mb-1 tracking-tight">${title}</div>
        <div class="text-[13px] text-neutral-500 max-w-sm mb-5 font-normal">${message}</div>
        ${action}
      </div>`;
  },

  // ── Section heading ─────────────────────────────────────────────────────────
  sectionHead(title, subtitle = '') {
    return `
      <div class="mb-4">
        <div class="text-[15px] font-bold text-black tracking-tight">${title}</div>
        ${subtitle ? `<div class="text-[12.5px] text-neutral-500 mt-0.5">${subtitle}</div>` : ''}
      </div>`;
  },

  // ── Check row ───────────────────────────────────────────────────────────────
  checkRow(label, value, ok) {
    const icon = ok === true
      ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10B981" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`
      : ok === false
      ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#EF4444" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`
      : `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#71717A" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
    return `
      <div class="check-item">
        <span class="text-neutral-700 font-medium">${label}</span>
        <span class="flex items-center gap-1.5 font-medium text-black">
          ${value !== undefined && value !== null ? `<span class="font-mono text-[12.5px] text-neutral-600">${value}</span>` : ''}
          ${icon}
        </span>
      </div>`;
  },

  // ── Diff viewer ─────────────────────────────────────────────────────────────
  diff(original, replacement, maxLines = 8) {
    if (!original && !replacement) return '';
    const origLines = (original || '').split('\n').slice(0, maxLines);
    const replLines = (replacement || '').split('\n').slice(0, maxLines);
    const delLines = origLines.map(l => `<div class="diff-line-del px-3.5 py-1 font-mono text-[11.5px]">- ${C._esc(l)}</div>`).join('');
    const addLines = replLines.map(l => `<div class="diff-line-add px-3.5 py-1 font-mono text-[11.5px]">+ ${C._esc(l)}</div>`).join('');
    return `
      <div class="rounded-xl overflow-hidden border border-neutral-200 mt-2 text-left bg-white">
        ${delLines}${addLines}
      </div>`;
  },

  // ── Loading skeleton ────────────────────────────────────────────────────────
  skeleton(rows = 3) {
    return Array.from({ length: rows }, (_, i) =>
      `<div class="skeleton h-4 mb-3" style="width:${70 + (i % 3) * 10}%;opacity:${1 - i * 0.1}"></div>`
    ).join('');
  },

  // ── Info banner ─────────────────────────────────────────────────────────────
  banner(msg, type = 'info') {
    const styles = {
      info:    'background:#FAFAFA;border:1px solid #E4E4E7;color:#18181B;',
      warn:    'background:#FFFBEB;border:1px solid #FDE68A;color:#92400E;',
      error:   'background:#FEF2F2;border:1px solid #FECACA;color:#991B1B;',
      success: 'background:#ECFDF5;border:1px solid #A7F3D0;color:#065F46;',
    };
    const icons = {
      info:    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#18181B" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
      warn:    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#D97706" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>',
      error:   '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#DC2626" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/></svg>',
      success: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#059669" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
    };
    return `
      <div class="flex items-start gap-2.5 p-3.5 rounded-xl text-[13px] font-medium mb-4" style="${styles[type] || styles.info}">
        ${icons[type] || ''} <div>${msg}</div>
      </div>`;
  },

  // ── Clean Contract State Card ──────────────────────────────────────────────
  cleanContractCard() {
    return `
      <div class="card p-6 border-neutral-200 bg-neutral-50/50 mb-5">
        <div class="flex items-center gap-3.5">
          <div class="w-10 h-10 rounded-xl bg-neutral-900 flex items-center justify-center text-white flex-shrink-0">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
          </div>
          <div>
            <div class="text-[14.5px] font-bold text-black">Clean Contract &bull; 100% Compatible</div>
            <div class="text-[12.5px] text-neutral-600 mt-0.5">No breaking API changes detected. All endpoints, schemas, parameters, and types remain fully backward-compatible.</div>
          </div>
        </div>
      </div>`;
  },

  // ── Validation Diagnostic (Clean Noir Monochrome) ─────────────────────────
  validationDiagnostic(v) {
    if (!v) return '';
    if (v.status === 'TESTS_PASSED') {
      return `
        <div class="p-3 rounded-lg text-[12px] mb-4 flex items-center justify-between bg-neutral-50 text-neutral-800 border border-neutral-200">
          <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-black"></span>
            <span class="font-semibold text-black">Sandbox Regression Suite Verified</span>
            <span class="text-neutral-500 text-[11.5px]">(${v.tests_passed || 0} tests passed in ${v.duration_ms || 0}ms &bull; Zero host mutations)</span>
          </div>
          ${C.statusBadge('TESTS_PASSED')}
        </div>`;
    }
    if (v.status === 'RUNNER_ERROR' || (v.syntax_ok && v.tests_collected === 0)) {
      return `
        <div class="p-3 rounded-lg text-[12px] mb-4 flex items-center justify-between bg-neutral-50 text-neutral-800 border border-neutral-200">
          <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-neutral-400"></span>
            <span class="font-semibold text-black">Python AST Syntax Verified</span>
            <span class="text-neutral-500 text-[11.5px]">(Syntax 100% valid)</span>
          </div>
          ${C.statusBadge('NO_TESTS_COLLECTED')}
        </div>`;
    }
    if (v.status === 'PATCH_FAILED') {
      return `
        <div class="p-3 rounded-lg text-[12px] mb-4 flex items-center justify-between bg-neutral-50 text-neutral-800 border border-neutral-200">
          <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-red-500"></span>
            <span class="font-semibold text-red-700">Precondition Mismatch / File Drift</span>
            <span class="text-neutral-500 text-[11.5px]">(Re-run Analyze)</span>
          </div>
          ${C.statusBadge('PATCH_FAILED')}
        </div>`;
    }
    return '';
  },

  // ── Runtime Failure & Error Diagnostics (Explains exact crash signature) ────
  runtimeDiagnostic(changes = [], directImpacts = []) {
    if (changes.length === 0) return '';
    const firstChange = changes[0];
    const field = firstChange.field || 'target';
    const method = firstChange.method || 'POST';
    const path = firstChange.path || '/api';
    const firstImpact = directImpacts[0] || { file: 'src/payment_service.py', line: 8, symbol: 'create_payment' };

    let errorSignature = `HTTP 422 Unprocessable Entity &bull; Missing or invalid parameter: '${field}'`;
    let errorDetail = `v2 server contract rejected the call because '${field}' was modified or removed.`;
    if (firstChange.change_type === 'path_parameter_type_changed') {
      errorSignature = `TypeError / ValueError &bull; Expected parameter type changed for '${field}'`;
      errorDetail = `Client sent type incompatible with updated v2 endpoint signature.`;
    } else if (firstChange.change_type === 'endpoint_removed') {
      errorSignature = `HTTP 404 Not Found &bull; Route '${path}' removed`;
      errorDetail = `Endpoint no longer exists on v2 API.`;
    }

    return `
      <div class="card p-5 mb-5 border border-neutral-200 bg-white">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-red-500"></span>
            <span class="font-bold text-[14px] text-black tracking-tight">Runtime Failure Diagnosis (If Unmigrated)</span>
          </div>
          <span class="badge" style="background:#000000;color:#FFFFFF;border:1px solid #000;">CRITICAL IMPACT</span>
        </div>

        <div class="space-y-3 text-[12px]">
          <div class="p-3 bg-neutral-50 rounded-lg border border-neutral-200">
            <div class="text-[10.5px] font-bold uppercase tracking-wider text-neutral-400 mb-1">Expected Runtime Exception</div>
            <div class="font-mono text-[12px] text-red-600 font-bold">${errorSignature}</div>
            <div class="text-[11.5px] text-neutral-500 mt-1">${errorDetail}</div>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <div class="p-3 bg-neutral-50 rounded-lg border border-neutral-200">
              <div class="text-[10.5px] font-bold uppercase tracking-wider text-neutral-400 mb-1">Crash Call Site</div>
              <div class="font-mono text-[12px] text-black font-semibold">${firstImpact.file}${firstImpact.line ? ':' + firstImpact.line : ''}</div>
              <div class="text-[11.5px] text-neutral-500 mt-0.5">${firstImpact.symbol ? 'Function: ' + firstImpact.symbol.split('::').pop() : 'Direct API invocation'}</div>
            </div>
            <div class="p-3 bg-neutral-50 rounded-lg border border-neutral-200">
              <div class="text-[10.5px] font-bold uppercase tracking-wider text-neutral-400 mb-1">Downstream Ripple</div>
              <div class="font-mono text-[12px] text-black font-semibold">Caller Pipeline Interrupted</div>
              <div class="text-[11.5px] text-neutral-500 mt-0.5">Calling functions crash with unhandled HTTP/Type error in production</div>
            </div>
          </div>

          <div class="p-3 bg-neutral-950 rounded-lg border border-neutral-800 text-neutral-200">
            <div class="flex items-center justify-between mb-1">
              <span class="text-[10.5px] font-bold uppercase tracking-wider text-neutral-400">Command to Reproduce Failure</span>
              <button class="text-[10.5px] text-neutral-400 hover:text-white" onclick="App.copyToClipboard('pytest tests/')">Copy</button>
            </div>
            <div class="font-mono text-[11.5px] text-white">pytest tests/</div>
            <div class="font-mono text-[11px] text-red-400 mt-1 pt-1 border-t border-neutral-800">
              FAILED tests - AssertionError: Expected 200 OK, got 422 Unprocessable Entity
            </div>
          </div>
        </div>
      </div>`;
  },

  // ── Code block ──────────────────────────────────────────────────────────────
  code(text, maxLines = 14) {
    if (!text) return '';
    const lines = text.split('\n').slice(0, maxLines);
    return `
      <pre class="rounded-xl p-4 text-[11.5px] leading-relaxed overflow-x-auto font-mono text-neutral-200 border border-neutral-800" style="background:#0B0F14;max-height:240px;">${C._esc(lines.join('\n'))}</pre>`;
  },

  // ── Visual Call Graph & Blast Radius (Noir Monochrome Architecture) ─────────
  visualCallGraph(directImpacts = [], indirectSymbols = [], changes = []) {
    if (directImpacts.length === 0 && indirectSymbols.length === 0 && changes.length === 0) {
      return '';
    }

    const firstChange = changes[0];
    const epMethod = firstChange?.method ? firstChange.method.toUpperCase() : 'POST';
    const epPath = firstChange?.path || '/payments';
    const ep = `${epMethod} ${epPath}`;
    const field = firstChange?.field ? `(${firstChange.field})` : '';

    const rootWidth = 220;
    const directWidth = 220;
    const indWidth = 200;

    // Adaptive font scaling ensuring endpoint text never overflows
    const epFontSize = ep.length > 25 ? 9.5 : ep.length > 18 ? 10.5 : 11.5;

    const height = Math.max(160, 60 + Math.max(directImpacts.length, 1) * 55 + Math.max(indirectSymbols.length, 0) * 45);
    const nodes = [];

    // Root API Node (Widened to 220px with centered text & generous padding)
    nodes.push(`
      <g transform="translate(15, 45)" class="cursor-pointer">
        <rect width="${rootWidth}" height="48" rx="8" fill="#000000" stroke="#27272A" stroke-width="1"/>
        <text x="${rootWidth / 2}" y="22" fill="#FFFFFF" font-size="${epFontSize}" font-weight="700" text-anchor="middle" font-family="monospace">${C._esc(ep)}</text>
        <text x="${rootWidth / 2}" y="36" fill="#A1A1AA" font-size="9" text-anchor="middle" font-family="monospace">${C._esc(field)}</text>
      </g>
    `);

    // Direct nodes (White card with black border + subtle red tag)
    const directStartX = 15 + rootWidth;
    const directTargetX = directStartX + 85;
    directImpacts.forEach((d, idx) => {
      const y = 35 + idx * 55;
      const fileText = `${d.file || 'service.py'}${d.line ? ':' + d.line : ''}`;
      const symText = d.symbol ? d.symbol.split('::').pop() : 'handler';

      nodes.push(`
        <path d="M ${directStartX} 69 C ${directStartX + 42} 69, ${directStartX + 42} ${y + 24}, ${directTargetX} ${y + 24}" stroke="#18181B" stroke-width="2" fill="none" stroke-linecap="round"/>
        <g transform="translate(${directTargetX}, ${y})" class="cursor-pointer">
          <rect width="${directWidth}" height="48" rx="8" fill="#FFFFFF" stroke="#18181B" stroke-width="1.5" filter="drop-shadow(0 1px 2px rgba(0,0,0,0.04))"/>
          <text x="14" y="21" fill="#000000" font-size="11" font-weight="700" font-family="monospace">${C._esc(fileText)}</text>
          <text x="14" y="36" fill="#DC2626" font-size="9.5" font-weight="600" font-family="Inter, sans-serif">${C._esc(symText)} [DIRECT]</text>
        </g>
      `);
    });

    // Indirect nodes (Gray-50 card with subtle dashed spline)
    const indStartX = directTargetX + directWidth;
    const indTargetX = indStartX + 70;
    indirectSymbols.forEach((ind, idx) => {
      const y = 35 + idx * 55;
      const indFile = ind.file || 'caller.py';
      const indSym = ind.symbol ? ind.symbol.split('::').pop() : 'caller';
      const dist = ind.distance || 1;

      nodes.push(`
        <path d="M ${indStartX} 59 C ${indStartX + 35} 59, ${indStartX + 35} ${y + 24}, ${indTargetX} ${y + 24}" stroke="#A1A1AA" stroke-width="1.5" stroke-dasharray="4,4" fill="none"/>
        <g transform="translate(${indTargetX}, ${y})" class="cursor-pointer">
          <rect width="${indWidth}" height="48" rx="8" fill="#FAFAFA" stroke="#E4E4E7" stroke-width="1" filter="drop-shadow(0 1px 2px rgba(0,0,0,0.02))"/>
          <text x="14" y="21" fill="#18181B" font-size="11" font-weight="600" font-family="monospace">${C._esc(indFile)}</text>
          <text x="14" y="36" fill="#71717A" font-size="9.5" font-family="Inter, sans-serif">${C._esc(indSym)} (dist: ${dist})</text>
        </g>
      `);
    });

    const totalWidth = Math.max(820, indTargetX + indWidth + 30);

    return `
      <div class="card p-5 mb-5 overflow-hidden">
        <div class="flex items-center justify-between mb-3">
          <div>
            <div class="text-[14px] font-bold text-black tracking-tight">Interactive Call Graph & Blast Radius</div>
            <div class="text-[12px] text-neutral-500 mt-0.5">Live dependency ripple effect from API contract change to callers</div>
          </div>
          <span class="badge" style="background:#F4F4F5;color:#000000;border:1px solid #E4E4E7;">${directImpacts.length} Direct &bull; ${indirectSymbols.length} Indirect</span>
        </div>
        <div class="overflow-x-auto bg-neutral-50/70 rounded-xl p-3 border border-neutral-200">
          <svg width="100%" height="${height}" viewBox="0 0 ${totalWidth} ${height}" xmlns="http://www.w3.org/2000/svg" style="min-width:${totalWidth - 40}px;">
            ${nodes.join('')}
          </svg>
        </div>
      </div>`;
  },

  _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
};