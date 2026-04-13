/**
 * game.js — Echoes of the Tainted Throne
 *
 * Encounter flow (every Explore action):
 *   Roll encounter type (70% travel / 20% combat / 10% discovery)
 *
 *   TRAVEL / DISCOVERY:
 *     Choices.disable → stream scene → monologue → Continue card → refreshState
 *
 *   COMBAT:
 *     resolve_combat (dice) → show roll divider
 *     → render 4 stance choices (fight/look/withdraw/submit)
 *     → wait for player pick  [waitForPlayerChoice]
 *     → stream scene with player_choice in encounter_data
 *     → monologue → Continue card → refreshState
 *
 *   REST / COMPANIONS:
 *     Same tail: stream → monologue → Continue card → refreshState
 *
 * Depends on: stats.js (Stats, Choices), stream_renderer.js (StreamRenderer)
 */

(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // Configuration
  // -------------------------------------------------------------------------

  const API_BASE      = 'http://localhost:8000';
  const CHAMPION_NAME = 'Aelindra';
  const SLOT_NAME     = 'Default';

  // Encounter pool and cooldown settings
  const ENCOUNTER_POOL          = ['imp_swarm', 'lupine_pack', 'cult_devotee'];
  const ENCOUNTER_COOLDOWN_DAYS = 3;   // same encounter can't fire within this window

  // Region data cache — fetched once per session per region
  const _regionCache = {};

  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------

  let SAVE_ID    = null;
  let GAME_STATE = null;
  let STYLE_SAMPLE = '';

  // Character sheet cache (fetched alongside save state)
  let _CHARACTER_SHEET = null;

  // Debug mode — toggled by D key
  let _debugMode = false;

  // Pending choice resolver — set by waitForPlayerChoice, cleared on card click
  let _pendingChoiceResolve = null;

  // -------------------------------------------------------------------------
  // API helpers
  // -------------------------------------------------------------------------

  async function apiPost(path, body) {
    const res = await fetch(`${API_BASE}${path}`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
    if (!res.ok) {
      const detail = await res.text();
      throw new Error(`${res.status} ${res.statusText}: ${detail}`);
    }
    return res.json();
  }

  async function apiGet(path) {
    const res = await fetch(`${API_BASE}${path}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  // -------------------------------------------------------------------------
  // State management
  // -------------------------------------------------------------------------

  async function refreshState() {
    if (!SAVE_ID) return;
    GAME_STATE = await apiGet(`/api/saves/${SAVE_ID}`);
    if (GAME_STATE.character_sheet) {
      _CHARACTER_SHEET = GAME_STATE.character_sheet;
    }
    Stats.update(GAME_STATE, _CHARACTER_SHEET);
    Choices.render(_buildContextualChoices(GAME_STATE));
  }

  function applyPartialChampion(champion) {
    if (!GAME_STATE) return;
    GAME_STATE = { ...GAME_STATE, champion };
    Stats.update(GAME_STATE, _CHARACTER_SHEET);
  }

  function applyPartialState(champion, world) {
    if (!GAME_STATE) return;
    GAME_STATE = { ...GAME_STATE, champion, world: world || GAME_STATE.world };
    Stats.update(GAME_STATE, _CHARACTER_SHEET);
  }

  // -------------------------------------------------------------------------
  // Choice helpers
  // -------------------------------------------------------------------------

  /**
   * Render choices and return a Promise that resolves with the chosen id.
   * The delegation handler checks _pendingChoiceResolve on every card click
   * and routes to this promise instead of _dispatch.
   */
  function waitForPlayerChoice(choices) {
    Choices.render(choices);
    Choices.enable();
    return new Promise(resolve => {
      _pendingChoiceResolve = resolve;
    });
  }

  /**
   * Show a single "Continue →" card and wait for the player to click it.
   */
  function awaitContinue() {
    return waitForPlayerChoice([{
      id:    '_continue',
      glyph: '→',
      title: 'Continue',
      desc:  'Return to the road',
    }]);
  }

  // -------------------------------------------------------------------------
  // Encounter choice cards (shown AFTER combat resolves, BEFORE scene streams)
  // -------------------------------------------------------------------------

  // Human-readable labels sent to the AI via encounter_data.player_choice_label
  const _CHOICE_LABELS = {
    enc_press:    'pressed the advantage aggressively',
    enc_finish:   'ended it with a single decisive strike',
    enc_drive:    'drove them off and let them flee',
    enc_mark:     'let the Kasyrra mark do its work',
    enc_survey:   'surveyed the area after the fight',
    enc_resist:   'fought back with everything remaining',
    enc_opening:  'looked for an opening through the pain',
    enc_withdraw: 'backed away slowly to avoid further provocation',
    enc_submit:   'stopped resisting — body and will both gave out',
    enc_endure:   'endured it without fighting back',
  };

  function _getEncounterChoices(combat) {
    const outcome = combat.outcome;
    const stage   = combat.champion.stage   ?? 0;
    const sub     = combat.champion.submission_score ?? 0;
    const mark    = combat.champion.kasyrra_mark_applied;

    if (outcome === 'win') {
      const choices = [
        { id: 'enc_press',  glyph: '⚔', title: 'Press the advantage', desc: `You have the upper hand — use it` },
        { id: 'enc_finish', glyph: '◉', title: 'End it quickly',       desc: 'One decisive move and it is over' },
        { id: 'enc_drive',  glyph: '→', title: 'Drive them off',        desc: 'Let them flee — the point is made' },
      ];
      if (mark) {
        choices.push({ id: 'enc_mark',   glyph: '✦', title: 'The mark held',   desc: 'Let their hesitation decide the rest' });
      } else {
        choices.push({ id: 'enc_survey', glyph: '⊕', title: 'Survey the area', desc: 'Check what they were guarding or fled from' });
      }
      return choices;
    }

    // Loss — calibrate by stage and submission
    const resistLabel = stage >= 2 ? 'Resist with everything left' : 'Fight back';
    const choices = [
      { id: 'enc_resist',   glyph: '⚔', title: resistLabel,            desc: 'Don\'t give them this without a fight' },
      { id: 'enc_opening',  glyph: '◉', title: 'Look for an opening',  desc: 'Wait for a moment to turn this around' },
      { id: 'enc_withdraw', glyph: '↩', title: 'Back away slowly',      desc: 'Withdraw without provoking further' },
    ];
    if (sub > 20 || stage > 0) {
      const submitLabel = sub > 60 ? 'Give in'         : 'Stop resisting';
      const submitDesc  = sub > 60
        ? 'Part of you has been here before. The gap between will and body is closing.'
        : 'The tactical decision. It is not the same as wanting this.';
      choices.push({ id: 'enc_submit', glyph: '·', title: submitLabel, desc: submitDesc });
    } else {
      choices.push({ id: 'enc_endure', glyph: '◎', title: 'Endure it', desc: 'Survive this encounter. That is enough.' });
    }
    return choices;
  }

  // -------------------------------------------------------------------------
  // Contextual default choice builder
  // -------------------------------------------------------------------------

  function _buildContextualChoices(gameState) {
    if (!gameState) return _defaultChoices();

    const champ  = gameState.champion || {};
    const world  = gameState.world    || {};
    const hp     = champ.current_hp   ?? 90;
    const maxHp  = champ.max_hp       ?? 90;
    const stage  = champ.stage        ?? 0;
    const corr   = champ.corruption   ?? 0;
    const sub    = champ.submission_score ?? 0;
    const morale = world.morale       ?? 70;
    const lowHp  = hp < maxHp * 0.3;

    // Incapacitation: desperate arousal + chastity locked simultaneously
    if (champ.arousal >= 90 && champ.chastity_locked) {
      return [{
        id: 'helpless', glyph: '✦',
        title: 'You have no choice',
        desc:  'The chastity device and your own body have conspired against you.',
        disabled: true,
      }];
    }

    let exploreTitle = 'Explore';
    let exploreDesc  = 'Move deeper into the road';

    if (lowHp) {
      exploreTitle = 'Press on (wounded)';
      exploreDesc  = 'Risk another encounter while still hurt';
    } else if (stage >= 3) {
      exploreTitle = 'Navigate carefully';
      exploreDesc  = 'Your changed body makes this harder than it used to be';
    } else if (champ.kasyrra_mark_applied) {
      exploreTitle = 'Follow the pull';
      exploreDesc  = 'The mark draws you forward — instinct or trap, hard to say';
    } else if (corr > 60) {
      exploreTitle = 'Take the darker path';
      exploreDesc  = 'Something in you knows these roads now';
    } else if (sub > 60) {
      exploreTitle = 'Step forward';
      exploreDesc  = 'The road doesn\'t care what you\'ve been through';
    }

    const restDesc = lowHp
      ? 'Your body is demanding recovery'
      : morale < 35
        ? 'The party needs to stop before something breaks'
        : 'Make camp before nightfall';

    const mapTitle = world.travel_destination
      ? `→ ${world.travel_destination}`
      : 'Map';
    const mapDesc = world.travel_destination
      ? `${world.travel_progress || 0}/${world.travel_steps_total || 10} steps toward ${world.travel_destination}`
      : 'View the region map and set a destination';

    return [
      { id: 'explore',    glyph: '⊕', title: exploreTitle, desc: exploreDesc },
      { id: 'rest',       glyph: '◎', title: 'Rest',        desc: restDesc },
      { id: 'companions', glyph: '⊏', title: 'Companions',  desc: 'Speak with those traveling with you' },
      { id: 'inventory',  glyph: '⊡', title: 'Inventory',   desc: 'Check what you carry' },
      { id: 'map',        glyph: '◈', title: mapTitle,       desc: mapDesc },
    ];
  }

  function _defaultChoices() {
    return [
      { id: 'explore',    glyph: '⊕', title: 'Explore',     desc: 'Move deeper into the road' },
      { id: 'rest',       glyph: '◎', title: 'Rest',         desc: 'Make camp before nightfall' },
      { id: 'companions', glyph: '⊏', title: 'Companions',   desc: 'Speak with those traveling with you' },
      { id: 'inventory',  glyph: '⊡', title: 'Inventory',    desc: 'Check what you carry' },
      { id: 'map',        glyph: '◈', title: 'Map',           desc: 'View the region map' },
    ];
  }

  // -------------------------------------------------------------------------
  // Encounter type roll (70 / 20 / 10)
  // -------------------------------------------------------------------------

  function _rollEncounterType() {
    const r = Math.random();
    if (r < 0.70) return 'travel';
    if (r < 0.90) return 'combat';
    return 'discovery';
  }

  /**
   * Pick a random encounter from the pool, respecting per-encounter cooldowns.
   * Cooldown state lives in localStorage (key: 'enc_cooldowns').
   */
  function _pickEncounterFromPool() {
    const today = GAME_STATE?.world?.in_game_day ?? 1;
    let cooldowns = {};
    try {
      cooldowns = JSON.parse(localStorage.getItem('enc_cooldowns') || '{}');
    } catch (_) {}

    const available = ENCOUNTER_POOL.filter(id => {
      const lastDay = cooldowns[id];
      return lastDay == null || (today - lastDay) >= ENCOUNTER_COOLDOWN_DAYS;
    });

    // If everything is on cooldown fall back to the full pool so the game never locks
    const pool   = available.length > 0 ? available : ENCOUNTER_POOL;
    const chosen = pool[Math.floor(Math.random() * pool.length)];

    // Record this encounter's fire day
    cooldowns[chosen] = today;
    try { localStorage.setItem('enc_cooldowns', JSON.stringify(cooldowns)); } catch (_) {}

    return chosen;
  }

  // -------------------------------------------------------------------------
  // UI helpers
  // -------------------------------------------------------------------------

  function scrollToBottom() {
    const el = document.querySelector('.narrative-scroll');
    if (el) el.scrollTop = el.scrollHeight;
  }

  function appendBlock(html) {
    const textEl = document.getElementById('narrative-text');
    if (!textEl) return;
    const block = document.createElement('div');
    block.className = 'scene-block';
    block.innerHTML = html;
    textEl.appendChild(block);
    scrollToBottom();
  }

  function appendError(message) {
    appendBlock(`<div class="scene-error">${esc(message)}</div>`);
  }

  function appendDivider(label) {
    appendBlock(
      `<p class="narrative-paragraph" style="color:var(--text-faint);font-size:.8rem;` +
      `letter-spacing:.1em;text-transform:uppercase;text-align:center;">— ${esc(label)} —</p>`
    );
  }

  function esc(str) {
    return String(str)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // -------------------------------------------------------------------------
  // Dream block renderer
  // -------------------------------------------------------------------------

  function _renderDreamBlock(dream) {
    if (!dream || !dream.text) return;
    const paras = dream.text.split(/\n\n+/).map(p =>
      `<p>${esc(p.trim()).replace(/\n/g, '<br>')}</p>`
    ).join('');
    appendBlock(`
      <div class="dream-block">
        <div class="dream-divider">— dream —</div>
        <div class="dream-title">${esc(dream.title || '')}</div>
        ${paras}
        <div class="dream-divider">— —</div>
      </div>`);
    scrollToBottom();
  }

  // -------------------------------------------------------------------------
  // Kasyrra scripted scene renderer
  // -------------------------------------------------------------------------

  async function _renderKasyrraScene(scene) {
    if (!scene || !scene.text) return;

    appendDivider(scene.title || 'A Visitor');

    const paras = scene.text.split(/\n\n+/).map(p =>
      `<p>${esc(p.trim()).replace(/\n/g, '<br>')}</p>`
    ).join('');
    appendBlock(`<div class="kasyrra-block">${paras}</div>`);
    scrollToBottom();
    await awaitContinue();

    // Companion reactions
    const reactions = scene.companion_reactions || {};
    const names = { saoirse: 'Saoirse', mireille: 'Mireille', tierlan: 'Tierlan' };
    for (const [key, line] of Object.entries(reactions)) {
      const label = names[key] || key;
      appendBlock(`<p class="companion-reaction"><em>${esc(label)}:</em> ${esc(line)}</p>`);
    }
    if (Object.keys(reactions).length > 0) {
      scrollToBottom();
      await awaitContinue();
    }

    // Aftermath
    if (scene.aftermath) {
      appendBlock(`<p class="scene-aftermath">${esc(scene.aftermath)}</p>`);
      scrollToBottom();
      await awaitContinue();
    }
  }

  // -------------------------------------------------------------------------
  // Gift block renderer
  // -------------------------------------------------------------------------

  async function _renderGiftBlock(gift) {
    if (!gift || !gift.discovery_scene) return;
    const paras = gift.discovery_scene.split(/\n\n+/).map(p =>
      `<p>${esc(p.trim()).replace(/\n/g, '<br>')}</p>`
    ).join('');

    // Build choice buttons
    const choices = [];
    if (gift.consume_effects) choices.push({ id: 'consume', label: 'Use it' });
    if (gift.wear_effects)    choices.push({ id: 'wear',    label: 'Wear it' });
    if (gift.keep_effects)    choices.push({ id: 'keep',    label: 'Keep it' });
    if (gift.destroy_effects) choices.push({ id: 'destroy', label: 'Destroy it' });
    if (gift.unlock_chastity) choices.push({ id: 'unlock',  label: 'Use the key' });

    const choiceHtml = choices.map(c =>
      `<button class="gift-choice-btn" data-choice="${c.id}">${esc(c.label)}</button>`
    ).join('');

    appendBlock(`
      <div class="gift-block">
        <div class="gift-name">${esc(gift.name || 'A Gift')}</div>
        ${paras}
        <div class="gift-choices" id="gift-choices-${esc(gift.id)}">${choiceHtml}</div>
      </div>`);
    scrollToBottom();

    // Wait for choice
    if (choices.length > 0) {
      const choiceId = await new Promise(resolve => {
        const container = document.getElementById(`gift-choices-${gift.id}`);
        if (!container) { resolve('keep'); return; }
        container.querySelectorAll('.gift-choice-btn').forEach(btn => {
          btn.addEventListener('click', () => {
            container.querySelectorAll('.gift-choice-btn').forEach(b => b.disabled = true);
            resolve(btn.dataset.choice);
          }, { once: true });
        });
      });

      try {
        await apiPost('/api/gift/apply', {
          save_id: SAVE_ID,
          gift_id: gift.id,
          choice:  choiceId,
        });
      } catch (e) {
        console.warn('[gift] Apply failed:', e.message);
      }
    }
  }

  // -------------------------------------------------------------------------
  // Inner monologue
  // -------------------------------------------------------------------------

  async function appendMonologue(sceneText) {
    if (!SAVE_ID || !sceneText || !sceneText.trim()) return;
    try {
      const result = await apiPost('/api/scene/introspect', {
        save_id:    SAVE_ID,
        scene_text: sceneText.slice(0, 1200),
      });
      if (result.monologue) {
        const paras = result.monologue
          .replace(/^\*+|\*+$/g, '')
          .split(/\n+/)
          .filter(p => p.trim());
        const html = paras.map(p => `<p>${esc(p.trim())}</p>`).join('');
        appendBlock(`<div class="monologue-block">${html}</div>`);
      }
    } catch (_) {
      // Non-critical — swallow
    }
  }

  // -------------------------------------------------------------------------
  // EXPLORE — rolls encounter type, branches to travel/combat/discovery
  // -------------------------------------------------------------------------

  async function handleExplore() {
    if (!SAVE_ID || !GAME_STATE) return;

    const type = _rollEncounterType();
    if (type === 'travel') {
      await _handleTravel();
    } else if (type === 'discovery') {
      await _handleDiscovery();
    } else {
      await _handleCombatEncounter();
    }
  }

  // ---- 70%: atmospheric travel scene ----

  async function _handleTravel() {
    Choices.disable();
    try {
      const world = GAME_STATE.world;

      // 70% chance: pull ambient line from region data (no AI call)
      if (Math.random() < 0.70) {
        const regionData = await _getRegionData(world?.region);
        const lines = regionData?.ambient_lines || [];
        if (lines.length > 0) {
          const line = lines[Math.floor(Math.random() * lines.length)];
          // Time variant: try to get time-specific atmosphere
          const timeAtmos = regionData?.time_variants?.[world?.time_of_day] || '';
          appendDivider('Traveling');
          const html = timeAtmos
            ? `<p class="narrative-paragraph">${esc(timeAtmos)}</p><p class="narrative-paragraph">${esc(line)}</p>`
            : `<p class="narrative-paragraph">${esc(line)}</p>`;
          appendBlock(html);
          await awaitContinue();
          await refreshState();
          return;
        }
      }

      // 30%: full AI stream
      const travelData = {
        scene_type: 'travel',
        notes:
          `The champion moves deeper into ${world?.region ?? 'the road'}. No enemy encounter. ` +
          `Day ${world?.in_game_day ?? 1}, ${world?.time_of_day ?? 'day'}. ` +
          `Write atmosphere, sensation, environment — not action. Short (200–350 words).`,
      };
      appendDivider('Traveling');
      const sceneText = await StreamRenderer.startStream(SAVE_ID, travelData, { style_sample: STYLE_SAMPLE });
      await appendMonologue(sceneText);
      _maybeFetchThinkBlock(sceneText);
      await awaitContinue();
      await refreshState();
    } catch (err) {
      appendError(`Travel failed: ${err.message}`);
      Choices.render(_buildContextualChoices(GAME_STATE));
    }
  }

  async function _getRegionData(regionName) {
    if (!regionName) return null;
    // Normalize region name to snake_case id (e.g. "Wolf-Road Edge" → "wolf_road")
    const id = regionName.toLowerCase()
      .replace(/[^a-z0-9\s]/g, '')
      .trim()
      .replace(/\s+/g, '_');
    if (_regionCache[id]) return _regionCache[id];
    try {
      const data = await apiGet(`/api/regions/${id}`);
      _regionCache[id] = data;
      return data;
    } catch (_) {
      return null;
    }
  }

  // ---- 10%: discovery scene ----

  async function _handleDiscovery() {
    Choices.disable();
    try {
      const world = GAME_STATE.world;
      const discoveryData = {
        scene_type: 'travel',
        notes:
          `The champion discovers something on the road — a remnant, a mystery, a sign. ` +
          `Region: ${world?.region ?? 'unknown'}. Day ${world?.in_game_day ?? 1}. ` +
          `Keep it brief and atmospheric. No mechanical consequence. 150–250 words.`,
      };
      appendDivider('Discovery');
      const sceneText = await StreamRenderer.startStream(SAVE_ID, discoveryData, { style_sample: STYLE_SAMPLE });
      await appendMonologue(sceneText);
      _maybeFetchThinkBlock(sceneText);
      await awaitContinue();
      await refreshState();
    } catch (err) {
      appendError(`Discovery failed: ${err.message}`);
      Choices.render(_buildContextualChoices(GAME_STATE));
    }
  }

  // ---- 20%: full combat encounter ----

  async function _handleCombatEncounter() {
    const encounterName = _pickEncounterFromPool();
    try {
      // === Phase 1: Resolve combat (dice + corruption/submission applied) ===
      const combat = await apiPost('/api/combat/resolve', {
        save_id:      SAVE_ID,
        encounter_id: encounterName,
      });

      // Capture old stage BEFORE applying partial update (for transition detection below)
      const stageBeforeCombat = GAME_STATE?.champion?.stage ?? 0;

      // Update sidebar immediately — corruption bar moves before scene starts
      applyPartialChampion(combat.champion);

      // Show roll outcome divider
      appendDivider(_combatRollSummary(combat));

      // If champion collapsed, show notice before the choice tray
      if (combat.carried_to_safety) {
        appendBlock(
          `<p class="narrative-paragraph" style="color:#8b2a2a;font-style:italic;">` +
          `You collapse. Your companions pull you back from the fight. ` +
          `The corruption marks the moment.</p>`
        );
      }

      // === Phase 2: Player picks narrative stance (reads from encounter JSON choices) ===
      const jsonChoices = (combat.encounter_data?.choices || []).map(c => ({
        id:     c.id,
        glyph:  c.glyph || '·',
        title:  c.label,
        desc:   c.desc,
        weight: c.id.includes('resist') ? 'good'
               : c.submission_event     ? 'bad'
               : 'neutral',
      }));
      const stanceChoices = jsonChoices.length > 0
        ? jsonChoices
        : _getEncounterChoices(combat);   // fallback to hardcoded
      const choiceId = await waitForPlayerChoice(stanceChoices);
      // Cards are now disabled (delegation handler called Choices.disable() on click)

      // Get the full choice object from encounter JSON (has the directive 'outcome' string)
      const allJsonChoices = combat.encounter_data?.choices || [];
      const chosenObj = allJsonChoices.find(c => c.id === choiceId);

      // Track repeat usage per save+encounter+choice
      let playerChoiceLabel = chosenObj?.outcome || _CHOICE_LABELS[choiceId] || choiceId;
      if (chosenObj && SAVE_ID) {
        const repeatKey = `choice_count_${SAVE_ID}_${encounterName}_${choiceId}`;
        const count = parseInt(localStorage.getItem(repeatKey) || '0') + 1;
        localStorage.setItem(repeatKey, count);
        if (count >= 3 && chosenObj.repeated_outcome) {
          playerChoiceLabel = chosenObj.repeated_outcome;
        }
      }

      // Build enriched encounter_data with the stance the player chose
      const encounterData = {
        ...combat.encounter_data,
        player_choice:       choiceId,
        player_choice_label: playerChoiceLabel,
      };

      // === Phase 3: Stream the scene ===
      const sceneText = await StreamRenderer.startStream(SAVE_ID, encounterData, { style_sample: STYLE_SAMPLE });

      // Stage transition notice
      if (combat.champion.stage > stageBeforeCombat) {
        appendBlock(
          `<p class="narrative-paragraph" style="color:var(--text-dim);font-style:italic;">` +
          `Stage transition: ${esc(combat.champion.stage_name)}</p>`
        );
      }

      // XP / level-up notice
      if (combat.xp_result) {
        const xp = combat.xp_result;
        if (xp.leveled_up) {
          appendBlock(
            `<p class="narrative-paragraph" style="color:var(--nar-stage,#e8a83a);font-weight:700;">` +
            `Level ${xp.new_level} — your capability has grown.</p>`
          );
        }
      }

      // === Phase 4: Inner monologue ===
      await appendMonologue(sceneText);
      _maybeFetchThinkBlock(sceneText);

      // === Phase 5: Continue card (clear end state) ===
      await awaitContinue();
      await refreshState();   // re-renders contextual choices and syncs sidebar

    } catch (err) {
      appendError(`Encounter failed: ${err.message}`);
      Choices.render(_buildContextualChoices(GAME_STATE));
    }
  }

  function _combatRollSummary(combat) {
    const outcome   = combat.outcome === 'win' ? 'Victory' : 'Defeated';
    const margin    = Math.abs(combat.margin);
    const qualifier = combat.margin >= 0
      ? (combat.margin >= 5 ? 'decisively' : 'narrowly')
      : (combat.margin <= -5 ? 'badly' : 'narrowly');
    const hpNote   = combat.hp_lost > 0 ? ` −${combat.hp_lost} HP.` : '';
    const markNote = combat.kasyrra_mark_hesitation ? ' The Mark gave pause.' : '';
    return `${outcome} — ${combat.enemy_display_name} · rolled ${combat.champion_roll} · ${qualifier} (${margin}).${hpNote}${markNote}`;
  }

  // -------------------------------------------------------------------------
  // REST — advance 8 hours + camp scene
  // -------------------------------------------------------------------------

  async function handleRest() {
    if (!SAVE_ID || !GAME_STATE) return;
    Choices.disable();

    try {
      const advance = await apiPost('/api/time/advance', { save_id: SAVE_ID, hours: 8 });
      applyPartialState(advance.champion, advance.world);

      const world     = advance.world || GAME_STATE.world;
      const timeLabel = _capitalize(world?.time_of_day || 'night');
      const day       = world?.in_game_day || GAME_STATE.world?.in_game_day || 1;

      const campData = {
        scene_type: 'camp',
        notes: [
          `The party rested for 8 hours.`,
          `It is now ${timeLabel}, Day ${day}.`,
          `Morale: ${world?.morale ?? GAME_STATE.world?.morale ?? 70}/100.`,
          advance.hp_restored > 0
            ? `HP restored during rest (+${advance.hp_restored}).`
            : '',
          advance.corruption_delta > 0
            ? `Passive corruption during rest (+${advance.corruption_delta.toFixed(2)}%).`
            : '',
        ].filter(Boolean).join(' '),
      };

      appendDivider(`Rest · Day ${day}`);

      // Dream sequence — render before the rest scene if triggered
      if (advance.dream) {
        _renderDreamBlock(advance.dream);
        await awaitContinue();
      }

      // Gift delivery — render before rest scene if triggered this day change
      if (advance.gift) {
        await _renderGiftBlock(advance.gift);
      }

      // Kasyrra first encounter — Day 3 scripted scene
      if (advance.kasyrra_scene) {
        await _renderKasyrraScene(advance.kasyrra_scene);
      }

      const sceneText = await StreamRenderer.startStream(SAVE_ID, campData, { style_sample: STYLE_SAMPLE });
      await appendMonologue(sceneText);
      _maybeFetchThinkBlock(sceneText);
      await awaitContinue();
      await refreshState();

    } catch (err) {
      appendError(`Rest failed: ${err.message}`);
      Choices.render(_buildContextualChoices(GAME_STATE));
    }
  }

  // -------------------------------------------------------------------------
  // COMPANIONS — random present companion scene
  // -------------------------------------------------------------------------

  async function handleCompanions() {
    if (!SAVE_ID || !GAME_STATE) return;
    Choices.disable();

    try {
      const present = (GAME_STATE.companions || []).filter(c => c.is_present);
      if (present.length === 0) {
        appendBlock('<p class="narrative-paragraph">No companions are present.</p>');
        Choices.render(_buildContextualChoices(GAME_STATE));
        return;
      }

      const companion = present[Math.floor(Math.random() * present.length)];
      appendDivider(companion.name);

      // Try dialogue tree first
      let dialogueData = null;
      try {
        dialogueData = await apiGet(`/api/npc/dialogue/${encodeURIComponent(companion.name)}?save_id=${SAVE_ID}`);
      } catch (_) {
        // fall through to AI stream
      }

      if (dialogueData && dialogueData.opening) {
        // --- Dialogue tree path ---
        appendBlock(
          `<div class="monologue-block">` +
          `<p><em>${esc(dialogueData.opening)}</em></p>` +
          `</div>`
        );

        // Build response choices
        const responseChoices = (dialogueData.responses || []).map(r => ({
          id:    r.id,
          glyph: '·',
          title: r.text,
          desc:  '',
        }));

        if (responseChoices.length === 0) {
          responseChoices.push({ id: '_continue', glyph: '→', title: 'Continue', desc: '' });
        }

        const choiceId = await waitForPlayerChoice(responseChoices);

        if (choiceId !== '_continue') {
          try {
            const result = await apiPost(
              `/api/npc/dialogue/respond?save_id=${SAVE_ID}&npc_name=${encodeURIComponent(companion.name)}&response_id=${encodeURIComponent(choiceId)}`,
              {}
            );

            if (result.reply) {
              appendBlock(
                `<p class="narrative-paragraph"><em>${esc(result.reply)}</em></p>`
              );
            }

            if (result.rel_delta > 0) {
              appendBlock(
                `<p class="narrative-paragraph" style="color:var(--text-faint);font-size:.8rem;text-align:center;">` +
                `+${result.rel_delta} with ${esc(companion.name)}</p>`
              );
            } else if (result.rel_delta < 0) {
              appendBlock(
                `<p class="narrative-paragraph" style="color:#8b3a3a;font-size:.8rem;text-align:center;">` +
                `${result.rel_delta} with ${esc(companion.name)}</p>`
              );
            }
          } catch (_) {
            // Non-critical — just continue
          }
        }

        await awaitContinue();
        await refreshState();

      } else {
        // --- AI stream fallback ---
        const { eventId, notes } = _pickCompanionEvent(companion, GAME_STATE.champion, GAME_STATE.world);
        const companionData = {
          scene_type:     'companion',
          companion_name: companion.name,
          event_id:       eventId,
          notes,
        };
        const sceneText = await StreamRenderer.startStream(SAVE_ID, companionData, { style_sample: STYLE_SAMPLE });
        await appendMonologue(sceneText);
        _maybeFetchThinkBlock(sceneText);
        await awaitContinue();
        await refreshState();
      }

    } catch (err) {
      appendError(`Companion scene failed: ${err.message}`);
      Choices.render(_buildContextualChoices(GAME_STATE));
    }
  }

  function _pickCompanionEvent(companion, champion, world) {
    const corruption = champion?.corruption ?? 0;
    const stage      = champion?.stage      ?? 0;
    const morale     = world?.morale        ?? 70;
    const rel        = companion.relationship_level ?? 30;
    const name       = companion.name;

    if (stage >= 3) {
      return {
        eventId: 'stage_transition_response',
        notes:   `${name} and the Champion are at Stage ${stage} (${champion?.stage_name}). ` +
                 `Relationship ${rel}/100. Show how ${name} has practically adjusted — not emotionally.`,
      };
    }
    if (morale < 35) {
      return {
        eventId: 'morale_low',
        notes:   `Party morale is ${morale}/100. ${name} is carrying something they haven't named. ` +
                 `Quiet conversation, not a crisis. Relationship ${rel}/100.`,
      };
    }
    if (corruption > 45 && stage >= 2) {
      return {
        eventId: 'transformation_concern',
        notes:   `Champion is Stage ${stage} — changes undeniable. ${name} has noticed. ` +
                 `Corruption ${corruption.toFixed(1)}%. The conversation they haven't had yet. Relationship ${rel}/100.`,
      };
    }
    if (rel >= 70) {
      return {
        eventId: 'deep_trust_moment',
        notes:   `Relationship ${rel}/100. Something real can be said. This is that moment.`,
      };
    }
    return {
      eventId: 'check_in',
      notes:   `${name} approaches during a quiet moment. Day ${world?.in_game_day ?? 1}. ` +
               `Stage ${stage}. Relationship ${rel}/100. Corruption ${corruption.toFixed(1)}%.`,
    };
  }

  // -------------------------------------------------------------------------
  // INVENTORY — three-tab overlay
  // -------------------------------------------------------------------------

  function handleInventory() {
    _openInventory();
  }

  function _openInventory() {
    const overlay = document.getElementById('inventory-overlay');
    if (!overlay) return;
    overlay.setAttribute('aria-hidden', 'false');
    _populateItemsTab();
    _populateCodexTab();
    _switchInvTab('self');
    _generateSelfDescription();
  }

  function _closeInventory() {
    const overlay = document.getElementById('inventory-overlay');
    if (overlay) overlay.setAttribute('aria-hidden', 'true');
  }

  function _switchInvTab(tabId) {
    document.querySelectorAll('.inv-tab').forEach(btn => {
      const active = btn.dataset.tab === tabId;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('.inv-panel').forEach(panel => {
      const match = panel.id === `inv-${tabId}`;
      panel.hidden = !match;
      if (match) panel.classList.add('active');
      else panel.classList.remove('active');
    });
  }

  async function _generateSelfDescription() {
    if (!SAVE_ID) return;
    const panel = document.getElementById('inv-self');
    if (!panel) return;

    const champ = GAME_STATE?.champion  || {};
    const sheet = GAME_STATE?.character_sheet || _CHARACTER_SHEET || {};
    const championName = champ.name || CHAMPION_NAME || 'Aelindra';

    // --- Deterministic physical facts block ---
    const physicalLines = [];
    if (sheet.height)        physicalLines.push(`Height: ${sheet.height}`);
    if (sheet.build || champ.build) physicalLines.push(`Build: ${sheet.build || champ.build}`);
    if (sheet.hair_color || champ.hair_color) physicalLines.push(`Hair: ${sheet.hair_color || champ.hair_color}`);
    if (sheet.eye_color  || champ.eye_color)  physicalLines.push(`Eyes: ${sheet.eye_color  || champ.eye_color}`);
    if (sheet.scent)         physicalLines.push(`Scent: ${sheet.scent}`);
    if (sheet.stage_name || champ.stage_name) physicalLines.push(`Stage: ${sheet.stage_name || champ.stage_name}`);
    if (champ.corruption != null) physicalLines.push(`Corruption: ${Math.round(champ.corruption)}%`);

    const physicalHtml = physicalLines.length > 0
      ? `<div class="self-physical">${physicalLines.map(l =>
          `<span class="self-fact"><strong>${esc(l.split(':')[0])}:</strong> ${esc(l.split(':').slice(1).join(':').trim())}</span>`
        ).join('')}</div>`
      : '';

    // Show loading state immediately with the physical facts already visible
    panel.innerHTML = `
      ${physicalHtml}
      <div class="inv-loading" id="self-loading">
        <span class="inv-loading-text">${esc(championName)} examines herself…</span>
      </div>`;

    try {
      const result = await apiPost('/api/scene/self_describe', { save_id: SAVE_ID });
      const text   = result.description || '';
      const paras  = text.split(/\n\n+/).filter(p => p.trim());
      const aiHtml = paras.map(p =>
        `<p class="self-inner-prose">${esc(p.trim())}</p>`
      ).join('');

      panel.innerHTML = `
        ${physicalHtml}
        ${aiHtml || '<p class="inv-empty">Nothing to examine yet.</p>'}`;
    } catch (err) {
      const loadingDiv = document.getElementById('self-loading');
      if (loadingDiv) loadingDiv.remove();
      panel.insertAdjacentHTML('beforeend',
        `<p class="inv-empty" style="color:#8b3a3a;">${esc(err.message)}</p>`);
    }
  }

  function _populateItemsTab() {
    if (!GAME_STATE?.champion) return;
    const champ = GAME_STATE.champion;
    const panel = document.getElementById('inv-items');
    if (!panel) return;

    const CURSED_NAMES = {
      chastity_flat:        'Chastity Device',
      cursed_harem_clothes: 'Cursed Harem Attire',
      cursed_plug:          'Binding Plug',
      kasyrras_collar:      "Kasyrra's Collar",
      pheromone_vial_trap:  'Pheromone Vial',
    };
    const CURSED_DESC = {
      chastity_flat:        'It cannot be removed without the right key. You stopped testing it some time ago.',
      cursed_harem_clothes: 'Enchanted. It cannot be taken off. You are aware, constantly, of how much it reveals.',
      cursed_plug:          'Bound in place by something you cannot see. Its presence is impossible to forget.',
      kasyrras_collar:      'You received this. You are not sure whether wearing it was a choice.',
      pheromone_vial_trap:  'Something was activated. You are still feeling it.',
    };

    const cursed = champ.cursed_items  || [];
    const toys   = champ.active_toys   || [];
    const marks  = (champ.active_statuses || []).filter(s =>
      ['kasyrra_marked', 'broodmarked', 'corruption_marked'].includes(s.effect_id)
    );

    // Equipment slots section
    const equip = champ.equipment_slots || {};
    const SLOT_LABELS = {
      head: 'Head', body: 'Body', legs: 'Legs', hands: 'Hands',
      main_hand: 'Main Hand', accessory: 'Accessory', cursed_slot: 'Cursed Slot',
    };
    const SLOT_ORDER = ['head', 'body', 'legs', 'hands', 'main_hand', 'accessory', 'cursed_slot'];
    const hasEquipment = SLOT_ORDER.some(s => equip[s]);

    let equipHtml = '';
    if (hasEquipment) {
      equipHtml = '<div class="inv-section-label">Equipment</div>';
      SLOT_ORDER.forEach(slot => {
        const item = equip[slot];
        const label = SLOT_LABELS[slot] || slot;
        equipHtml += `<div class="item-entry">
          <div class="item-slot-label">${esc(label)}</div>
          ${item
            ? `<div class="item-name">${esc(item.name || item.id || 'Unknown')}</div>
               ${item.effects && Object.keys(item.effects).length > 0
                 ? `<div class="item-desc">${Object.entries(item.effects).map(([k,v]) => `${k} ${v > 0 ? '+' : ''}${v}`).join(', ')}</div>`
                 : ''}`
            : `<div class="item-name" style="color:var(--text-faint);font-style:italic;">—</div>`
          }
        </div>`;
      });
    }

    if (cursed.length === 0 && toys.length === 0 && marks.length === 0 && !hasEquipment) {
      panel.innerHTML = '<p class="inv-empty">Nothing in inventory. This will not last.</p>';
      return;
    }

    let html = '';
    [...cursed, ...toys].forEach(id => {
      html += `<div class="item-entry">
        <div class="item-name">${esc(CURSED_NAMES[id] || id)}</div>
        ${CURSED_DESC[id] ? `<div class="item-desc">${esc(CURSED_DESC[id])}</div>` : ''}
      </div>`;
    });
    marks.forEach(m => {
      const dur = m.duration != null ? ` — ${m.duration}h remaining` : ' — permanent';
      html += `<div class="item-entry">
        <div class="item-name">${esc(m.display_name)}${esc(dur)}</div>
        <div class="item-desc">A mark that does not wash off.</div>
      </div>`;
    });
    panel.innerHTML = (hasEquipment ? equipHtml + '<div class="inv-section-label" style="margin-top:.8rem">Carried</div>' : '') + html || '<p class="inv-empty">Nothing in inventory. This will not last.</p>';
  }

  async function _populateCodexTab() {
    if (!SAVE_ID) return;
    const panel = document.getElementById('codex-entries');
    if (!panel) return;

    // Load reputation as first codex section
    try {
      const rep = await apiGet(`/api/saves/${SAVE_ID}/reputation`);
      let repHtml = '<div class="codex-section-title">Faction Standing</div>';
      Object.entries(rep).forEach(([key, val]) => {
        repHtml += `
          <div class="codex-faction-entry">
            <div class="codex-faction-name">${esc(val.label)}</div>
            <div class="codex-faction-meta">${esc(val.descriptor)} (${val.score})</div>
          </div>`;
      });

      // Load codex entries
      const CODEX_IDS = ['the_marches', 'kasyrra', 'corrupted_lupines', 'corruption_forms'];
      let entriesHtml = '<div class="codex-section-title" style="margin-top:1.2rem">Lore</div>';
      for (const id of CODEX_IDS) {
        try {
          const entry = await apiGet(`/api/codex/${id}?save_id=${SAVE_ID}`);
          if (entry.locked) {
            entriesHtml += `
              <div class="codex-entry locked">
                <div class="codex-entry-title">— Locked —</div>
                <div class="codex-entry-unlock">${esc(entry.unlock_condition)}</div>
              </div>`;
          } else {
            entriesHtml += `
              <div class="codex-entry">
                <div class="codex-entry-title">${esc(entry.title)}</div>
                <div class="codex-entry-content">${esc(entry.content)}</div>
              </div>`;
          }
        } catch (_) {}
      }

      panel.innerHTML = repHtml + entriesHtml;
    } catch (err) {
      panel.innerHTML = `<p class="inv-empty">Could not load codex.</p>`;
    }
  }

  // -------------------------------------------------------------------------
  // MAP — show region connections and travel destination selector
  // -------------------------------------------------------------------------

  async function handleMap() {
    if (!SAVE_ID || !GAME_STATE) return;
    Choices.disable();

    try {
      const world      = GAME_STATE.world;
      const regionData = await _getRegionData(world?.region);
      const connections = regionData?.connections || [];

      appendDivider('Map');

      let html = `<p class="narrative-paragraph" style="color:var(--text-dim);">` +
        `<strong>${esc(world?.region || 'Unknown')}</strong> — ` +
        `Day ${world?.in_game_day || 1}, ${world?.time_of_day || 'morning'}.</p>`;

      if (regionData?.description) {
        html += `<p class="narrative-paragraph">${esc(regionData.description)}</p>`;
      }

      // Show POIs
      const pois = regionData?.points_of_interest || [];
      if (pois.length > 0) {
        html += `<p class="narrative-paragraph" style="color:var(--text-faint);font-size:.85rem;">` +
          `<em>Points of interest: ${pois.map(p => esc(p.name || p)).join(', ')}</em></p>`;
      }

      // Show current travel progress
      if (world.travel_destination) {
        const progress = world.travel_progress || 0;
        const total    = world.travel_steps_total || 10;
        html += `<p class="narrative-paragraph" style="color:var(--text-accent);">` +
          `Traveling to <strong>${esc(world.travel_destination)}</strong> — ` +
          `${progress}/${total} steps.</p>`;
      }

      appendBlock(html);

      // Build destination choices from region connections
      const destChoices = connections.map(c => ({
        id:    `map_dest_${typeof c === 'string' ? c : c.id || c.name}`,
        glyph: '→',
        title: typeof c === 'string' ? c : (c.name || c),
        desc:  typeof c === 'object' && c.desc ? c.desc : 'Set as travel destination',
      }));

      destChoices.push({ id: '_continue', glyph: '·', title: 'Stay here', desc: 'Continue in this region' });

      const choice = await waitForPlayerChoice(destChoices);

      if (choice !== '_continue' && choice.startsWith('map_dest_')) {
        const destName = choice.slice('map_dest_'.length);
        await apiPost(`/api/travel/set-destination?save_id=${SAVE_ID}&destination=${encodeURIComponent(destName)}`, {});
        appendBlock(`<p class="narrative-paragraph" style="color:var(--text-dim);">` +
          `<em>Destination set: ${esc(destName)}.</em></p>`);
      }

      await refreshState();
    } catch (err) {
      appendError(`Map failed: ${err.message}`);
      Choices.render(_buildContextualChoices(GAME_STATE));
    }
  }

  // -------------------------------------------------------------------------
  // AI Panel
  // -------------------------------------------------------------------------

  function _initAIPanel() {
    const toggle      = document.getElementById('ai-panel-toggle');
    const body        = document.getElementById('ai-panel-body');
    const checkbox    = document.getElementById('ai-show-thinking');
    const thinkSect   = document.getElementById('ai-think-section');
    const styleInput  = document.getElementById('ai-style-input');
    const styleApply  = document.getElementById('ai-style-apply');
    const styleStatus = document.getElementById('ai-style-status');

    if (!toggle || !body) return;

    // Restore thinking preference
    const stored = localStorage.getItem('aiShowThinking') === 'true';
    if (checkbox) {
      checkbox.checked = stored;
      if (thinkSect) thinkSect.hidden = !stored;
    }

    // Restore style sample
    const storedStyle = sessionStorage.getItem('aiStyleSample') || '';
    if (styleInput) styleInput.value = storedStyle;
    if (storedStyle) STYLE_SAMPLE = storedStyle;

    // Tab switching for 4-tab debug panel
    document.querySelectorAll('.debug-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        const tabId = btn.dataset.dtab;
        document.querySelectorAll('.debug-tab').forEach(b => b.classList.toggle('active', b === btn));
        document.querySelectorAll('.debug-panel').forEach(panel => {
          const match = panel.id === `dp-${tabId}`;
          panel.classList.toggle('active', match);
          panel.hidden = !match;
        });
        if (tabId === 'state')   _refreshDebugState();
        if (tabId === 'world')   _refreshDebugWorld();
        if (tabId === 'choices') _refreshDebugChoices();
        if (tabId === 'ai')      _refreshDebugAI();
      });
    });

    // Panel open/close
    toggle.addEventListener('click', () => {
      const open = body.hidden;
      body.hidden = !open;
      toggle.classList.toggle('active', !body.hidden);
      if (!body.hidden) {
        apiGet('/api/ai/status')
          .then(r => {
            _setTextById('ai-model-name', r.configured_model || '—');
          })
          .catch(() => {});
        _refreshDebugState();
      }
    });

    // Thinking checkbox
    if (checkbox && thinkSect) {
      checkbox.addEventListener('change', () => {
        thinkSect.hidden = !checkbox.checked;
        localStorage.setItem('aiShowThinking', String(checkbox.checked));
      });
    }

    // Style apply
    if (styleApply && styleInput) {
      styleApply.addEventListener('click', () => {
        STYLE_SAMPLE = styleInput.value.trim();
        sessionStorage.setItem('aiStyleSample', STYLE_SAMPLE);
        if (styleStatus) {
          styleStatus.textContent = STYLE_SAMPLE ? 'Style applied for this session.' : 'Style cleared.';
          setTimeout(() => { if (styleStatus) styleStatus.textContent = ''; }, 3000);
        }
      });
    }
  }

  function _refreshDebugState() {
    const champEl = document.getElementById('dp-champion-json');
    const sheetEl = document.getElementById('dp-sheet-json');
    const sinEl   = document.getElementById('dp-sin-json');

    if (champEl && GAME_STATE?.champion) {
      // Full champion dump
      champEl.textContent = JSON.stringify(GAME_STATE.champion, null, 2);
    }
    if (sheetEl && _CHARACTER_SHEET) {
      sheetEl.textContent = JSON.stringify(_CHARACTER_SHEET, null, 2);
    }
    if (sinEl && GAME_STATE?.champion) {
      const c = GAME_STATE.champion;
      sinEl.textContent = JSON.stringify({
        sin:               c.sin,
        tone_preference:   c.tone_preference,
        gender:            c.gender,
        hair_color:        c.hair_color,
        eye_color:         c.eye_color,
        build:             c.build,
        prologue_done:     c.prologue_done,
        attraction_current: _CHARACTER_SHEET?.attraction_current,
        attraction_arc_score: _CHARACTER_SHEET?.attraction_arc_score,
      }, null, 2);
    }
  }

  function _refreshDebugWorld() {
    const worldEl     = document.getElementById('dp-world-json');
    const flagsEl     = document.getElementById('dp-flags-json');
    const dreamEl     = document.getElementById('dp-dream-gift-json');
    const cooldownEl  = document.getElementById('dp-cooldowns-json');
    const travelEl    = document.getElementById('dp-travel-json');

    if (worldEl && GAME_STATE?.world) {
      worldEl.textContent = JSON.stringify(GAME_STATE.world, null, 2);
    }

    // Story flags from save state
    if (flagsEl && GAME_STATE?.story_flags) {
      flagsEl.textContent = JSON.stringify(GAME_STATE.story_flags, null, 2);
    } else if (flagsEl) {
      flagsEl.textContent = '(not loaded — story_flags not in state)';
    }

    // Dream + gift trigger status extracted from story flags
    if (dreamEl && GAME_STATE?.story_flags) {
      const flags = GAME_STATE.story_flags;
      const dreamStatus = {};
      const giftStatus  = {};
      for (const [k, v] of Object.entries(flags)) {
        if (k.startsWith('dream_done_'))      dreamStatus[k.replace('dream_done_', '')] = v ? 'triggered' : 'pending';
        if (k.startsWith('gift_triggered_'))  giftStatus[k.replace('gift_triggered_', '')] = v ? 'delivered' : 'pending';
      }
      dreamEl.textContent = JSON.stringify({ dreams: dreamStatus, gifts: giftStatus }, null, 2);
    } else if (dreamEl) {
      dreamEl.textContent = '{}';
    }

    if (cooldownEl) {
      try {
        cooldownEl.textContent = JSON.stringify(
          JSON.parse(localStorage.getItem('enc_cooldowns') || '{}'), null, 2
        );
      } catch (_) { cooldownEl.textContent = '{}'; }
    }
    if (travelEl && GAME_STATE?.travel) {
      travelEl.textContent = JSON.stringify(GAME_STATE.travel, null, 2);
    } else if (travelEl && GAME_STATE?.world) {
      travelEl.textContent = JSON.stringify({
        destination: GAME_STATE.world.travel_destination,
        progress: GAME_STATE.world.travel_progress,
        total: GAME_STATE.world.travel_steps_total,
      }, null, 2);
    }
  }

  function _refreshDebugChoices() {
    const choicesEl = document.getElementById('dp-choices-json');
    if (!choicesEl) return;
    const cards = [...document.querySelectorAll('#choice-cards .choice-card')].map(c => ({
      id: c.dataset.choiceId,
      disabled: c.classList.contains('disabled'),
      weight: c.dataset.debugWeight || null,
    }));
    choicesEl.textContent = JSON.stringify(cards, null, 2);
  }

  async function _refreshDebugAI() {
    if (!SAVE_ID) return;
    const promptEl = document.getElementById('dp-last-prompt');
    if (!promptEl) return;
    promptEl.textContent = 'Fetching…';
    try {
      const result = await apiGet(`/api/debug/last-prompt?save_id=${SAVE_ID}`);
      promptEl.textContent = result.prompt || result.note || '(none)';
    } catch (e) {
      promptEl.textContent = `Error: ${e.message}`;
    }
  }

  async function _maybeFetchThinkBlock(sceneText) {
    const checkbox = document.getElementById('ai-show-thinking');
    if (!checkbox || !checkbox.checked || !SAVE_ID || !sceneText) return;
    const content = document.getElementById('ai-think-content');
    if (!content) return;
    content.textContent = 'Fetching…';
    try {
      const result = await apiPost('/api/scene/debug-think', {
        save_id:    SAVE_ID,
        scene_text: sceneText.slice(0, 800),
      });
      content.textContent = result.think_block || '(no think block returned)';
    } catch (err) {
      content.textContent = `Error: ${err.message}`;
    }
  }

  function _setTextById(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val ?? '—';
  }

  // -------------------------------------------------------------------------
  // Utilities
  // -------------------------------------------------------------------------

  function _capitalize(str) {
    return str ? str.charAt(0).toUpperCase() + str.slice(1) : '';
  }

  /** Normal action dispatch — only fires when _pendingChoiceResolve is null. */
  function _dispatch(choiceId) {
    if (!SAVE_ID) {
      appendError('Game not loaded yet. Check that the server is running.');
      return;
    }
    // Prologue actions — allowed even when GAME_STATE is not yet fully loaded
    if (choiceId === 'prologue_skip') {
      _handlePrologueSkip();
      return;
    }
    if (choiceId.startsWith('prologue_continue:')) {
      const actId = choiceId.slice('prologue_continue:'.length);
      _handlePrologueContinue(actId);
      return;
    }
    if (!GAME_STATE) {
      appendError('Game not loaded yet. Check that the server is running.');
      return;
    }
    const handlers = {
      explore:    handleExplore,
      rest:       handleRest,
      companions: handleCompanions,
      inventory:  handleInventory,
      map:        handleMap,
      helpless:   () => {},
    };
    const handler = handlers[choiceId];
    if (handler) handler();
  }

  // -------------------------------------------------------------------------
  // Init
  // -------------------------------------------------------------------------

  async function init(saveId = null) {
    try {
      // Show loading state while fetching
      const textEl = document.getElementById('narrative-text');
      if (textEl) {
        const loadBlock = document.createElement('div');
        loadBlock.className = 'scene-block';
        loadBlock.id = 'init-loading-block';
        loadBlock.innerHTML = '<div class="scene-loading">Loading the Marches<span class="loading-dots"><span>.</span><span>.</span><span>.</span></span></div>';
        textEl.appendChild(loadBlock);
      }

      const targetId = saveId || 1;
      const state = await apiGet(`/api/saves/${targetId}`);
      SAVE_ID    = state.save_id;
      GAME_STATE = state;
      // Store character sheet if included in response
      if (state.character_sheet) {
        _CHARACTER_SHEET = state.character_sheet;
      }
      // Remove loading block
      const loadingBlock = document.getElementById('init-loading-block');
      if (loadingBlock) loadingBlock.remove();

      Stats.update(state, _CHARACTER_SHEET);

      // Check prologue — if not done, enter prologue mode before normal gameplay
      if (state.champion && state.champion.prologue_done === false) {
        await _runPrologue(state.champion.background || 'warrior');
        return;
      }

      Choices.render(_buildContextualChoices(state));
    } catch (err) {
      console.warn('[game] Failed to load save:', err.message);
      appendBlock(
        `<div class="scene-error">Failed to load save. ` +
        `Start the backend: <code>uvicorn main:app --reload</code></div>`
      );
    }
  }

  // -------------------------------------------------------------------------
  // Prologue system
  // -------------------------------------------------------------------------

  async function _runPrologue(background) {
    if (!SAVE_ID) return;

    // Fetch current act
    let prologue;
    try {
      prologue = await apiGet(`/api/prologue/status?save_id=${SAVE_ID}`);
    } catch (e) {
      console.warn('[prologue] Could not fetch status:', e.message);
      Choices.render(_buildContextualChoices(GAME_STATE));
      return;
    }

    if (prologue.prologue_done) {
      Choices.render(_buildContextualChoices(GAME_STATE));
      return;
    }

    // Render skip option + first act
    _renderPrologueAct(prologue, background);
  }

  function _renderPrologueAct(prologue, background) {
    const act = prologue.act_data;
    if (!act) {
      Choices.render(_buildContextualChoices(GAME_STATE));
      return;
    }

    // Pick variant text if available
    let bodyText = '';
    if (act.variants && act.variants[background]) {
      bodyText = act.variants[background];
    } else if (act.steps && act.steps.length > 0) {
      // Explore tutorial — show first step, we'll sequence through
      bodyText = act.steps.map(s => `<strong>${s.prompt}</strong>\n\n${s.result}`).join('\n\n—\n\n');
    } else if (act.scene) {
      bodyText = act.scene;
    } else {
      bodyText = act.title || '';
    }

    // Render act as prologue block
    const html = `<div class="prologue-block">
      <div class="prologue-title">${esc(act.title || '')}</div>
      ${act.subtitle ? `<div class="prologue-subtitle">${esc(act.subtitle)}</div>` : ''}
      <div class="prologue-body">${bodyText.replace(/\n\n/g, '</p><p>').replace(/^/, '<p>').replace(/$/, '</p>')}</div>
    </div>`;
    appendBlock(html);
    scrollToBottom();

    // Build choices: Continue + Skip Prologue
    const choices = [
      { id: `prologue_continue:${act.id}`, glyph: '→', title: 'Continue', desc: '' },
    ];
    if (prologue.current_act !== 'act_1_portal') {
      // Allow skip after first act
      choices.push({ id: 'prologue_skip', glyph: '»', title: 'Skip Prologue', desc: 'Begin at day 3 with all companions.' });
    }
    Choices.render(choices);
  }

  async function _handlePrologueContinue(actId) {
    try {
      const res = await apiPost(`/api/prologue/advance?save_id=${SAVE_ID}&completed_act=${actId}`, {});
      if (res.prologue_done) {
        // Prologue complete — refresh state and enter game
        await refreshState();
        appendDivider('The road opens.');
        Choices.render(_buildContextualChoices(GAME_STATE));
      } else {
        // Next act
        const background = GAME_STATE?.champion?.background || 'warrior';
        _renderPrologueAct({ prologue_done: false, current_act: res.next_act, act_data: res.next_act_data }, background);
      }
    } catch (e) {
      appendError(`Prologue error: ${e.message}`);
    }
  }

  async function _handlePrologueSkip() {
    try {
      const res = await apiPost(`/api/prologue/skip?save_id=${SAVE_ID}`, {});
      GAME_STATE = { ...GAME_STATE, champion: res.champion, world: res.world };
      Stats.update(GAME_STATE, _CHARACTER_SHEET);
      if (res.skip_text) {
        appendBlock(`<div class="prologue-block skip"><p>${res.skip_text.replace(/\n\n/g,'</p><p>')}</p></div>`);
      }
      appendDivider('Day 3. The companions are here.');
      Choices.render(_buildContextualChoices(GAME_STATE));
    } catch (e) {
      appendError(`Skip error: ${e.message}`);
    }
  }

  // -------------------------------------------------------------------------
  // DOM ready
  // -------------------------------------------------------------------------

  document.addEventListener('DOMContentLoaded', function () {

    console.log('game.js loaded');
    console.log('choice-cards container:', document.getElementById('choice-cards'));
    console.log('static cards found:',
      [...document.querySelectorAll('.choice-card')].map(c => c.dataset.choiceId));

    StreamRenderer.init({
      scrollEl: '.narrative-scroll',
      textEl:   '#narrative-text',
      apiBase:  API_BASE,
    });

    // -------------------------------------------------------------------
    // Central click delegation on #choice-cards
    // Checks _pendingChoiceResolve first — if set, this is an encounter
    // stance card or Continue card, not a normal action dispatch.
    // -------------------------------------------------------------------
    const choiceTray = document.getElementById('choice-cards');
    if (choiceTray) {
      choiceTray.addEventListener('click', function (e) {
        const card = e.target.closest('.choice-card');
        if (!card || card.classList.contains('disabled')) return;
        const choiceId = card.dataset.choiceId;
        if (!choiceId) return;

        if (_pendingChoiceResolve) {
          // Encounter-mode: resolve the waiting promise and disable cards
          const resolve = _pendingChoiceResolve;
          _pendingChoiceResolve = null;
          Choices.disable();
          resolve(choiceId);
          return;
        }

        // Normal mode: dispatch to action handlers
        _dispatch(choiceId);
      });
    }

    // Note: all card click routing goes through the delegation handler above.
    // Choices.onSelect is not used — delegation is the sole click source.

    // Inventory overlay
    const invClose = document.getElementById('inventory-close');
    if (invClose) invClose.addEventListener('click', _closeInventory);

    const invOverlay = document.getElementById('inventory-overlay');
    if (invOverlay) {
      invOverlay.addEventListener('click', e => {
        if (e.target === invOverlay) _closeInventory();
      });
    }

    document.querySelectorAll('.inv-tab').forEach(btn => {
      btn.addEventListener('click', () => _switchInvTab(btn.dataset.tab));
    });

    // Debug mode toggle (D key)
    document.addEventListener('keydown', function (e) {
      if ((e.key === 'd' || e.key === 'D') && !e.ctrlKey && !e.altKey) {
        // Don't toggle if focus is in a text input
        if (document.activeElement?.tagName === 'INPUT' ||
            document.activeElement?.tagName === 'TEXTAREA') return;
        _debugMode = !_debugMode;
        document.body.classList.toggle('debug-mode', _debugMode);
      }
    });

    _initAIPanel();
    // Hand off to save screen — it calls init(saveId) when slot is selected
    if (window.SaveScreen) {
      SaveScreen.init(init);
    } else {
      init();  // fallback if save_screen.js not loaded
    }
  });

}());
