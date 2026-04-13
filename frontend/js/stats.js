/**
 * Stats — sidebar game state renderer
 * Choices — choice tray card renderer
 *
 * Call Stats.update(gameState) whenever the backend returns updated state.
 * gameState shape matches GET /api/saves/{id} response.
 *
 * Choices.render(choices) accepts an array of choice objects:
 *   { id, glyph, title, desc, disabled }
 * and renders clickable cards into #choice-cards.
 * Set Choices.onSelect(fn) to handle a card click.
 */

// =============================================================================
// Stats module
// =============================================================================

const Stats = (() => {

  // ---------------------------------------------------------------------------
  // Color path → display name
  // ---------------------------------------------------------------------------

  const PATH_LABELS = {
    violet:  'Violet',
    crimson: 'Crimson',
    teal:    'Teal',
    rose:    'Rose',
    amber:   'Amber',
    grey:    'Grey',
    ivory:   'Ivory',
  };

  // ---------------------------------------------------------------------------
  // Status chip classification
  // ---------------------------------------------------------------------------

  const CHIP_CLASS = {
    chastity_flat:        'cursed',
    cursed_harem_clothes: 'cursed',
    cursed_plug:          'cursed',
    temporary_enslavement:'cursed',
    high_arousal:         'arousal',
    desperate_arousal:    'arousal',
    pheromone_drunk:      'arousal',
    kasyrra_marked:       'mark',
    broodmarked:          'mark',
    corruption_marked:    'mark',
  };

  // ---------------------------------------------------------------------------
  // Time-of-day → display string
  // ---------------------------------------------------------------------------

  const TIME_DISPLAY = {
    dawn:    'Dawn',
    morning: 'Morning',
    midday:  'Midday',
    evening: 'Evening',
    night:   'Night',
  };

  // ---------------------------------------------------------------------------
  // Main entry point
  // ---------------------------------------------------------------------------

  function update(gameState, characterSheet) {
    if (!gameState) return;
    const { champion, world, kasyrra, companions } = gameState;
    // Use character_sheet from gameState OR from explicit parameter
    const sheet = characterSheet || gameState.character_sheet || null;

    _updateChampionHeader(champion);
    _updateHP(champion);
    _updateCorruption(champion);
    _updateCoreStats(champion, sheet);
    _updateStatuses(champion);
    _updateCompanions(companions);
    _updateWorld(world, gameState.travel);
    _updateSlideout(champion, sheet);
  }

  // Sin symbol map
  const SIN_SYMBOLS = {
    pride: '♦', lust: '♥', sloth: '♠', wrath: '♣',
    envy: '★', greed: '$', gluttony: '●',
  };
  const SIN_COLORS = {
    pride: '#d4af37', lust: '#c0392b', sloth: '#7f8c8d', wrath: '#e74c3c',
    envy: '#8e44ad', greed: '#27ae60', gluttony: '#e67e22',
  };

  // Attraction threshold labels
  const ATTRACTION_LABELS = {
    'female-leaning': { label: 'Female-Leaning', color: '#d4729a' },
    'uncertain':      { label: 'Uncertain',       color: '#a89060' },
    'male-drawn':     { label: 'Male-Drawn',      color: '#4a8abf' },
    'seeking dominance': { label: 'Seeking Dominance', color: '#8e44ad' },
    'devoted':        { label: 'Devoted',          color: '#c0392b' },
  };

  // ---------------------------------------------------------------------------
  // Champion header
  // ---------------------------------------------------------------------------

  function _updateChampionHeader(c) {
    _setText('champion-name',  c.name || '—');
    _setText('champion-stage', `Stage ${c.stage} · ${c.stage_name || ''}`);

    // Sin badge
    const sin = (c.sin || 'pride').toLowerCase();
    const sinBadge = document.getElementById('sin-badge');
    if (sinBadge) {
      sinBadge.textContent = SIN_SYMBOLS[sin] || '♦';
      sinBadge.style.color = SIN_COLORS[sin] || '#d4af37';
      sinBadge.title = `Sin: ${sin.charAt(0).toUpperCase() + sin.slice(1)}`;
    }

    // Level + XP bar
    const level     = c.level     ?? 1;
    const xp        = c.xp_current ?? c.xp ?? 0;
    const xpToNext  = c.xp_to_next ?? 100;
    const xpPct     = xpToNext > 0 ? Math.min(100, (xp / xpToNext) * 100) : 0;
    _setText('champion-level', level);
    _setText('xp-label', `${xp}/${xpToNext} XP`);
    const xpFill = document.getElementById('xp-fill');
    if (xpFill) xpFill.style.width = `${xpPct}%`;

    // Attraction indicator (only show if not default / if score meaningful)
    const arcLabel = c.attraction_current || c.gender_attraction || '';
    const arcScore = c.attraction_arc_score ?? 0;
    const arcEl    = document.getElementById('attraction-indicator');
    const arcLabelEl = document.getElementById('attraction-label');
    if (arcEl && arcLabelEl && arcLabel && arcScore > 0) {
      const info = ATTRACTION_LABELS[arcLabel.toLowerCase()] || { label: arcLabel, color: '#888' };
      arcLabelEl.textContent = info.label;
      arcLabelEl.style.color = info.color;
      arcEl.hidden = false;
    } else if (arcEl) {
      arcEl.hidden = true;
    }
  }

  // ---------------------------------------------------------------------------
  // HP bar
  // ---------------------------------------------------------------------------

  function _updateHP(c) {
    const current = c.current_hp ?? 90;
    const max     = c.max_hp     ?? 90;
    const pct     = max > 0 ? (current / max) * 100 : 0;

    _setText('stat-hp', `${current}/${max}`);

    const fill = document.getElementById('hp-fill');
    if (fill) {
      fill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
      fill.classList.toggle('hp-low',      pct < 40 && pct >= 20);
      fill.classList.toggle('hp-critical', pct < 20);
    }
  }

  // ---------------------------------------------------------------------------
  // Corruption bar + submission mini-bar
  // ---------------------------------------------------------------------------

  function _updateCorruption(c) {
    const wrapper = document.getElementById('corruption-bar-wrapper');
    if (!wrapper) return;

    const path       = (c.color_path || 'grey').toLowerCase();
    const corruption = Math.min(100, Math.max(0, c.corruption || 0));
    const submission = Math.min(100, Math.max(0, c.submission_score || 0));

    wrapper.dataset.path = path;

    const fill = wrapper.querySelector('.corruption-bar-fill');
    if (fill) {
      fill.style.width = `${corruption}%`;
      fill.classList.toggle('high', corruption >= 80);
    }

    _setText('corruption-value',      `${corruption.toFixed(1)}%`);
    _setText('corruption-path-label', PATH_LABELS[path] || path);
    _setText('corruption-stage-label', c.stage_name || '');

    const ponr = c.ponr_locks || {};
    _setPonrMarker(wrapper, 1, ponr['1']);
    _setPonrMarker(wrapper, 2, ponr['2']);
    _setPonrMarker(wrapper, 3, ponr['3']);
    _setPonrMarker(wrapper, 4, ponr['4']);

    const subFill = wrapper.querySelector('.submission-bar-fill');
    if (subFill) subFill.style.width = `${submission}%`;
  }

  function _setPonrMarker(wrapper, gate, locked) {
    const marker = wrapper.querySelector(`.stage-marker[data-gate="${gate}"]`);
    if (marker) marker.classList.toggle('locked', !!locked);
  }

  // ---------------------------------------------------------------------------
  // Core stats + bar rows
  // ---------------------------------------------------------------------------

  function _updateCoreStats(c, sheet) {
    const BASE = 10;

    _setStatVal('stat-force',    c.force,    BASE);
    _setStatVal('stat-grace',    c.grace,    BASE);
    _setStatVal('stat-resolve',  c.resolve,  BASE);
    _setStatVal('stat-presence', c.presence, BASE);

    // Submission score (now visible)
    const sub = Math.round(c.submission_score || 0);
    const subEl = document.getElementById('stat-submission');
    if (subEl) {
      subEl.textContent = sub;
      subEl.className = 'stat-val'
        + (sub >= 70 ? ' penalised' : sub >= 40 ? '' : '');
    }

    // Arousal bar
    const arousal = c.arousal || 0;
    const aroFill = document.getElementById('arousal-fill');
    if (aroFill) {
      aroFill.style.width = `${arousal}%`;
      aroFill.classList.toggle('high',      arousal >= 70 && arousal < 90);
      aroFill.classList.toggle('desperate', arousal >= 90);
    }
    _setText('stat-arousal', `${arousal}`);

    // Essence / Mana bar
    const essence    = c.essence ?? 100;
    const essenceFill = document.getElementById('essence-fill');
    if (essenceFill) {
      essenceFill.style.width = `${Math.max(0, Math.min(100, essence))}%`;
      essenceFill.classList.toggle('low', essence < 30);
    }
    _setText('stat-essence', `${essence}`);

    // Feminization bar
    const fem     = c.feminization ?? 0;
    const femFill = document.getElementById('fem-fill');
    if (femFill) {
      femFill.style.width = `${Math.max(0, Math.min(100, fem))}%`;
      femFill.classList.toggle('high', fem >= 50);
    }
    _setText('stat-feminization', `${fem}%`);

    // Feminization physical descriptors from character sheet
    const femDescEl = document.getElementById('fem-descriptors');
    if (femDescEl && sheet) {
      const words = [];
      if (sheet.race && sheet.race !== 'Human') {
        // Short form: "Vulpine-Touched" → "Vulpine"
        const raceParts = sheet.race.split(/[-\s]/);
        words.push(raceParts[0]);
      }
      if (fem >= 40 && fem < 70) words.push('Softening');
      else if (fem >= 70) words.push('Transformed');
      if (sheet.height_cm) words.push(`${Math.round(sheet.height_cm)}cm`);
      femDescEl.textContent = words.length > 0 ? words.join(' \u00b7 ') : '';
    } else if (femDescEl) {
      femDescEl.textContent = '';
    }
  }

  function _setStatVal(id, value, base) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value;
    el.classList.toggle('penalised', value < base);
    el.classList.toggle('boosted',   value > base);
  }

  // ---------------------------------------------------------------------------
  // Active status chips
  // ---------------------------------------------------------------------------

  function _updateStatuses(c) {
    const container = document.getElementById('active-statuses');
    if (!container) return;

    // Arousal states shown via bar — exclude from chips
    const statuses = (c.active_statuses || []).filter(
      s => s.effect_id !== 'high_arousal' && s.effect_id !== 'desperate_arousal'
    );

    if (statuses.length === 0) {
      container.innerHTML = '<span class="status-none">—</span>';
      return;
    }

    container.innerHTML = '<div class="status-chips">'
      + statuses.map(s => {
          const cls = CHIP_CLASS[s.effect_id] || '';
          const dur = s.duration != null ? ` (${s.duration}h)` : '';
          return `<span class="status-chip ${cls}" title="${s.effect_id}">${s.display_name}${dur}</span>`;
        }).join('')
      + '</div>';
  }

  // ---------------------------------------------------------------------------
  // Companions
  // ---------------------------------------------------------------------------

  function _updateCompanions(companions) {
    const container = document.getElementById('companions-list');
    if (!container || !companions) return;

    if (companions.length === 0) {
      container.innerHTML = '<span class="status-none">—</span>';
      return;
    }

    container.innerHTML = companions.map(c => {
      const dotClass = c.is_present ? 'present' : 'absent';
      const rel      = typeof c.relationship_level === 'number'
                       ? `${c.relationship_level}/100`
                       : '—';
      return `
        <div class="companion-entry">
          <span class="companion-dot ${dotClass}"></span>
          <span class="companion-name">${_esc(c.name)}</span>
          <span class="companion-rel">${rel}</span>
        </div>`;
    }).join('');
  }

  // ---------------------------------------------------------------------------
  // World state
  // ---------------------------------------------------------------------------

  const WEATHER_LABEL = {
    clear: 'Clear', cloudy: 'Cloudy', rain: 'Rain', fog: 'Fog',
    storm: 'Storm', tainted_mist: 'Tainted Mist',
  };
  const WEATHER_COLOR = {
    clear: '#d4af37', cloudy: '#888', rain: '#4a8abf', fog: '#a0a0a0',
    storm: '#c0392b', tainted_mist: '#8e44ad',
  };

  function _updateWorld(world, travel) {
    if (!world) return;

    _setText('world-region', world.region || '—');
    _setText('world-time',
      `${TIME_DISPLAY[world.time_of_day] || world.time_of_day || '—'} · Day ${world.in_game_day || 1}`
    );
    _setText('world-supplies', `${world.supplies ?? '—'} days`);

    const moraleEl = document.getElementById('world-morale');
    if (moraleEl) {
      const m = world.morale ?? 0;
      moraleEl.textContent = `${m}/100`;
      moraleEl.className = 'stat-val'
        + (m < 30 ? ' penalised' : m >= 70 ? ' boosted' : '');
    }

    // Weather indicator
    const weatherKey  = (world.weather || 'clear').toLowerCase().replace(' ', '_');
    const weatherSym  = world.weather_symbol || '☀';
    const weatherDays = world.weather_days ?? null;
    _setText('weather-symbol', weatherSym);
    _setText('weather-label',  WEATHER_LABEL[weatherKey] || weatherKey);
    const wDaysEl = document.getElementById('weather-days');
    if (wDaysEl) {
      wDaysEl.textContent = weatherDays != null ? `${weatherDays}d` : '';
    }
    const wSymEl = document.getElementById('weather-symbol');
    if (wSymEl) wSymEl.style.color = WEATHER_COLOR[weatherKey] || '#888';

    // Travel progress bar
    const travelRow = document.getElementById('travel-progress-row');
    if (travelRow && travel && travel.destination) {
      const pct = travel.progress_pct ?? 0;
      _setText('travel-dest', travel.destination);
      const tFill = document.getElementById('travel-bar-fill');
      if (tFill) tFill.style.width = `${pct}%`;
      travelRow.hidden = false;
    } else if (travelRow) {
      travelRow.hidden = true;
    }
  }

  // ---------------------------------------------------------------------------
  // Extended stats slide-out panel
  // ---------------------------------------------------------------------------

  const SIN_DESCRIPTIONS = {
    pride:    'Seeks mastery — transformation as proof of worth',
    lust:     'Drawn to pleasure — corruption reads as desire',
    sloth:    'Yields to ease — the path of least resistance',
    wrath:    'Fights the change — every yielding costs something',
    envy:     'Covets what corruption offers — half-resisting',
    greed:    'Collects power — views each stage as acquisition',
    gluttony: 'Consumes and is consumed — excess in all things',
  };

  const TONE_LABELS = {
    dread:    'Dread — transformation as loss',
    conflict: 'Conflict — compelling and distressing',
    relief:   'Relief — disturbed by how little they resist',
  };

  const SUB_LABELS = [
    [76, 'Devoted'],
    [51, 'Yielding'],
    [26, 'Wavering'],
    [ 0, 'Resistant'],
  ];

  function _updateSlideout(c, sheet) {
    // Feminization
    const fem = c.feminization ?? 0;
    _setText('sl-fem-val', `${fem}%`);
    const slFemFill = document.getElementById('sl-fem-fill');
    if (slFemFill) slFemFill.style.width = `${Math.min(100, fem)}%`;

    // Submission
    const sub = Math.round(c.submission_score || 0);
    _setText('sl-sub-val', sub);
    const slSubFill = document.getElementById('sl-sub-fill');
    if (slSubFill) slSubFill.style.width = `${Math.min(100, sub)}%`;
    const subLabel = SUB_LABELS.find(([min]) => sub >= min)?.[1] ?? 'Resistant';
    _setText('sl-sub-label', subLabel);

    // Attraction arc
    const arcLabel = c.attraction_current || c.gender_attraction || '';
    const arcInfo  = ATTRACTION_LABELS[(arcLabel || '').toLowerCase()] || { label: arcLabel || '—', color: '#888' };
    const slArc = document.getElementById('sl-attraction');
    if (slArc) {
      slArc.textContent = arcInfo.label;
      slArc.style.color = arcInfo.color;
    }

    // Sin
    const sin = (c.sin || '').toLowerCase();
    const sinEl = document.getElementById('sl-sin');
    if (sinEl) {
      sinEl.textContent = sin ? sin.charAt(0).toUpperCase() + sin.slice(1) : '—';
      sinEl.style.color = SIN_COLORS[sin] || '#888';
    }
    _setText('sl-sin-desc', SIN_DESCRIPTIONS[sin] || '');

    // Tone
    const tone = (c.tone_preference || '').toLowerCase();
    _setText('sl-tone', TONE_LABELS[tone] || (tone ? tone : '—'));

    // Background + physical from sheet
    _setText('sl-background', c.background
      ? c.background.charAt(0).toUpperCase() + c.background.slice(1)
      : '—');

    if (sheet) {
      const heightCm = sheet.height_cm;
      _setText('sl-height', heightCm ? `${heightCm} cm` : (sheet.height || '—'));
      _setText('sl-hair', sheet.hair_color || '—');
      _setText('sl-eyes', sheet.eye_color  || '—');
    } else {
      _setText('sl-height', '—');
      _setText('sl-hair',   '—');
      _setText('sl-eyes',   '—');
    }
  }

  // Slide-out toggle — called once on DOMContentLoaded from game.js
  function initSlideoutToggle() {
    const btn    = document.getElementById('stats-slideout-toggle');
    const panel  = document.getElementById('stats-slideout');
    if (!btn || !panel) return;

    btn.addEventListener('click', () => {
      const open = panel.getAttribute('aria-hidden') === 'false';
      panel.setAttribute('aria-hidden', String(open));
      btn.setAttribute('aria-expanded', String(!open));
      btn.textContent = open ? '◁' : '▷';
    });
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value ?? '—';
  }

  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  return { update, initSlideoutToggle };

})();


// =============================================================================
// Choices module
// =============================================================================

const Choices = (() => {

  let _onSelect = null;

  /**
   * Register a handler called with the choice id when a card is clicked.
   * @param {(id: string) => void} fn
   */
  function onSelect(fn) {
    _onSelect = fn;
  }

  /**
   * Render an array of choice objects into #choice-cards.
   *
   * @param {Array<{id:string, glyph:string, title:string, desc:string, disabled?:boolean}>} choices
   */
  function render(choices) {
    const container = document.getElementById('choice-cards');
    if (!container) return;

    if (!choices || choices.length === 0) {
      container.innerHTML = '<div class="choice-card disabled"><div class="choice-body"><div class="choice-title">—</div></div></div>';
      return;
    }

    container.innerHTML = choices.map(c => {
      const disabled   = c.disabled ? ' disabled' : '';
      const glyph      = c.glyph   || '·';
      const debugAttr  = c.weight !== undefined ? ` data-debug-weight="${_esc(String(c.weight))}"` : '';
      return `
        <div class="choice-card${disabled}" data-choice-id="${_esc(c.id)}"${debugAttr}>
          <div class="choice-glyph">${_esc(glyph)}</div>
          <div class="choice-body">
            <div class="choice-title">${_esc(c.title)}</div>
            ${c.desc ? `<div class="choice-desc">${_esc(c.desc)}</div>` : ''}
          </div>
        </div>`;
    }).join('');

    // Click handling is done entirely via event delegation on #choice-cards in game.js.
    // Do NOT attach per-card listeners here — they would fire a second dispatch
    // alongside the delegation handler and cause double-action bugs.
  }

  /**
   * Disable all choice cards (during streaming).
   */
  function disable() {
    const container = document.getElementById('choice-cards');
    if (!container) return;
    container.querySelectorAll('.choice-card').forEach(c => c.classList.add('disabled'));
  }

  /**
   * Re-enable all choice cards.
   */
  function enable() {
    const container = document.getElementById('choice-cards');
    if (!container) return;
    container.querySelectorAll('.choice-card').forEach(c => c.classList.remove('disabled'));
  }

  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  return { onSelect, render, disable, enable };

})();
