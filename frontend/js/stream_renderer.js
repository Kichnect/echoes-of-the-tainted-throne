/**
 * StreamRenderer — SSE token stream → typewriter narrative
 *
 * Connects to POST /api/scene/stream via the Fetch + ReadableStream API
 * (not EventSource, since this endpoint requires POST with a JSON body).
 *
 * Token flow:
 *   server sends: data: {"token": "word "}\n\n
 *   server sends: data: [DONE]\n\n
 *   server sends: data: {"error": "..."}\n\n  (on failure)
 *
 * Paragraph rendering:
 *   The raw text is accumulated and re-rendered on each token.
 *   \n\n splits become separate <p> elements.
 *   The last paragraph gets the blinking cursor until [DONE].
 *
 * Scroll behaviour:
 *   Auto-scrolls to bottom while streaming.
 *   Stops auto-scrolling if user has manually scrolled up.
 *   Resumes when user scrolls back to the bottom.
 */

const StreamRenderer = (() => {

  // -------------------------------------------------------------------------
  // Internal state
  // -------------------------------------------------------------------------

  let _scrollEl       = null;   // the .narrative-scroll container
  let _textEl         = null;   // the .narrative-text container inside scroll
  let _apiBase        = 'http://localhost:8000';
  let _isStreaming    = false;
  let _rawText        = '';
  let _userScrolled   = false;  // true if user has scrolled up during streaming
  let _currentBlock   = null;   // the active .scene-block div
  let _abortCtrl      = null;   // AbortController for the current fetch
  let _idleTimer      = null;   // setTimeout handle for the 30s idle cutoff
  const _IDLE_MS      = 30_000; // close stream if no token arrives within this window

  // -------------------------------------------------------------------------
  // Init
  // -------------------------------------------------------------------------

  /**
   * @param {object} opts
   * @param {string}  opts.scrollEl   - selector for the scroll container
   * @param {string}  opts.textEl     - selector for the text target
   * @param {string}  [opts.apiBase]  - base URL (default localhost:8000)
   */
  function init(opts = {}) {
    _scrollEl = document.querySelector(opts.scrollEl || '.narrative-scroll');
    _textEl   = document.querySelector(opts.textEl   || '#narrative-text');
    if (opts.apiBase) _apiBase = opts.apiBase;

    // Track whether the user has manually scrolled away from the bottom
    if (_scrollEl) {
      _scrollEl.addEventListener('scroll', _onUserScroll, { passive: true });
    }
  }

  // -------------------------------------------------------------------------
  // Public: start a streaming scene
  // -------------------------------------------------------------------------

  /**
   * Start streaming a scene.
   *
   * @param {number} saveId
   * @param {object} encounterData  - scene_type, enemy, combat_result, etc.
   * @param {object} [opts]         - optional overrides: { style_sample }
   * @returns {Promise<string>}     - resolves with the full accumulated prose text
   */
  async function startStream(saveId, encounterData, opts = {}) {
    if (_isStreaming) {
      cancel();
    }

    _isStreaming    = true;
    _rawText        = '';
    _userScrolled   = false;

    // Create a new scene block (scenes stack with dividers)
    _currentBlock = _createSceneBlock();
    _showLoading(_currentBlock);

    _abortCtrl = new AbortController();

    const requestBody = {
      save_id:      saveId,
      encounter_data: encounterData,
      style_sample: opts.style_sample || '',
    };

    try {
      const response = await fetch(`${_apiBase}/api/scene/stream`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(requestBody),
        signal:  _abortCtrl.signal,
      });

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}: ${response.statusText}`);
      }

      // Clear the loading spinner now that the connection is established
      _clearLoading(_currentBlock);
      _resetIdleTimer();   // start the 30s idle watchdog

      const reader  = response.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // SSE lines end with \n\n; process complete frames
        const frames = buffer.split('\n\n');
        buffer = frames.pop(); // last element may be incomplete

        for (const frame of frames) {
          _processFrame(frame.trim());
        }
      }

    } catch (err) {
      if (err.name === 'AbortError') return _rawText;
      _clearLoading(_currentBlock);
      _showError(_currentBlock, err.message);
    } finally {
      _finalize();
    }

    return _rawText;
  }

  // -------------------------------------------------------------------------
  // Public: cancel the current stream
  // -------------------------------------------------------------------------

  function cancel() {
    if (_abortCtrl) {
      _abortCtrl.abort();
      _abortCtrl = null;
    }
    _finalize();
  }

  // -------------------------------------------------------------------------
  // Public: clear all narrative content
  // -------------------------------------------------------------------------

  function clear() {
    cancel();
    if (_textEl) _textEl.innerHTML = '';
    _rawText      = '';
    _currentBlock = null;
    _isStreaming  = false;
  }

  // -------------------------------------------------------------------------
  // SSE frame processing
  // -------------------------------------------------------------------------

  function _processFrame(frame) {
    if (!frame.startsWith('data:')) return;

    const payload = frame.slice(5).trim();

    if (payload === '[DONE]') {
      _finalize();
      return;
    }

    let parsed;
    try {
      parsed = JSON.parse(payload);
    } catch {
      return;
    }

    if (parsed.error) {
      _clearLoading(_currentBlock);
      _showError(_currentBlock, parsed.error);
      _finalize();
      return;
    }

    if (parsed.token) {
      _appendToken(parsed.token);
    }
  }

  // -------------------------------------------------------------------------
  // Token → DOM
  // -------------------------------------------------------------------------

  function _appendToken(token) {
    if (!_currentBlock) return;

    _rawText += token;
    _renderText(_currentBlock, _rawText, /* withCursor */ true);
    _autoScroll();
    _resetIdleTimer();
  }

  function _resetIdleTimer() {
    if (_idleTimer) clearTimeout(_idleTimer);
    _idleTimer = setTimeout(() => {
      if (!_isStreaming) return;
      // No token for 30 s — append ellipsis and close cleanly
      _rawText += '\u2026';  // …
      if (_currentBlock) _renderText(_currentBlock, _rawText, false);
      cancel();
    }, _IDLE_MS);
  }

  function _clearIdleTimer() {
    if (_idleTimer) { clearTimeout(_idleTimer); _idleTimer = null; }
  }

  /**
   * Render rawText into the scene block.
   * Splits on \n\n → separate <p> elements.
   * The last paragraph gets the blinking cursor if withCursor is true.
   */
  function _renderText(block, rawText, withCursor) {
    // Split into paragraphs (double newline = paragraph break)
    const paragraphs = rawText.split(/\n\n+/).map(p => p.replace(/\n/g, ' ').trim()).filter(Boolean);

    if (paragraphs.length === 0) return;

    const html = paragraphs.map((text, i) => {
      const isLast  = i === paragraphs.length - 1;
      const cursor  = (withCursor && isLast) ? '<span class="narrative-cursor"></span>' : '';
      const escaped = _escapeHtml(text);
      const colored = _colorizeNarrative(escaped);
      return `<p class="narrative-paragraph">${colored}${cursor}</p>`;
    }).join('');

    block.innerHTML = html;
  }

  // -------------------------------------------------------------------------
  // Finalize: remove cursor, mark done
  // -------------------------------------------------------------------------

  function _finalize() {
    _isStreaming = false;
    _clearIdleTimer();

    if (_currentBlock && _rawText) {
      // Re-render without cursor
      _renderText(_currentBlock, _rawText, /* withCursor */ false);
    }

    // Scroll to bottom one last time
    if (_scrollEl && !_userScrolled) {
      _scrollEl.scrollTop = _scrollEl.scrollHeight;
    }
  }

  // -------------------------------------------------------------------------
  // Loading / error states
  // -------------------------------------------------------------------------

  function _showLoading(block, label) {
    const text = label || 'Composing scene';
    block.innerHTML = `<div class="scene-loading">${_escapeHtml(text)}<span class="loading-dots"><span>.</span><span>.</span><span>.</span></span></div>`;
  }

  function _clearLoading(block) {
    const loader = block.querySelector('.scene-loading');
    if (loader) loader.remove();
  }

  function _showError(block, message) {
    const el = document.createElement('div');
    el.className = 'scene-error';
    el.textContent = `Scene generation failed: ${message}`;
    block.appendChild(el);
  }

  // -------------------------------------------------------------------------
  // Scene block creation
  // -------------------------------------------------------------------------

  function _createSceneBlock() {
    const block = document.createElement('div');
    block.className = 'scene-block';
    if (_textEl) _textEl.appendChild(block);
    return block;
  }

  // -------------------------------------------------------------------------
  // Auto-scroll
  // -------------------------------------------------------------------------

  function _autoScroll() {
    if (!_scrollEl || _userScrolled) return;
    _scrollEl.scrollTop = _scrollEl.scrollHeight;
  }

  function _onUserScroll() {
    if (!_scrollEl || !_isStreaming) return;

    const distFromBottom = _scrollEl.scrollHeight
                         - _scrollEl.scrollTop
                         - _scrollEl.clientHeight;

    // Consider "at bottom" if within 60px
    _userScrolled = distFromBottom > 60;
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  /**
   * Post-process escaped HTML narrative text to add colored emphasis spans.
   * Patterns detected (in order, non-overlapping):
   *   **text** or *text* → bold
   *   −N HP / +N HP      → red / green
   *   +N.N% corruption   → bold purple
   *   +N submission       → rose
   *   Stage N             → amber (only when followed by stage name)
   *   [Item Name]         → item span (teal)
   */
  /**
   * postProcess — runs on each completed escaped-HTML paragraph string.
   * Applies colored emphasis for game events, names, and locations.
   * Called from _renderText() after _escapeHtml().
   */
  function postProcess(html) {
    // Markdown bold/italic (author markup in pre-written scenes)
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Damage: (-N HP) format Gemma tends to use
    html = html.replace(/\((-\d+)\s*HP\)/g,
      '<span class="hit-damage">($1 HP)</span>');
    // Also catch: −N HP / -N HP without parens
    html = html.replace(/(−|\u2212|-)(\d+)\s*HP(?!\))/g,
      '<span class="hit-damage">−$2 HP</span>');
    html = html.replace(/\+(\d+)\s*HP/g,
      '<span class="nar-heal">+$1 HP</span>');

    // Corruption gains
    html = html.replace(/\(\+(\d+\.?\d*)\s*corruption\)/gi,
      '<span class="hit-corruption">(+$1 corruption)</span>');
    html = html.replace(/\+(\d+\.?\d*)\s*%?\s*corruption(?!\))/gi,
      '<span class="hit-corruption">+$1% corruption</span>');

    // Submission gains
    html = html.replace(/\(\+(\d+\.?\d*)\s*submission\)/gi,
      '<span class="hit-submission">(+$1 submission)</span>');
    html = html.replace(/\+(\d+\.?\d*)\s*submission(?!\))/gi,
      '<span class="hit-submission">+$1 submission</span>');

    // XP gains
    html = html.replace(/\(\+(\d+)\s*XP\)/gi,
      '<span class="hit-xp">(+$1 XP)</span>');

    // Stage references
    html = html.replace(/\b(Stage\s+[0-4])\b/g,
      '<span class="hit-stage">$1</span>');

    // [Item Name] in square brackets
    html = html.replace(/\[([^\]]+)\]/g,
      '<span class="nar-item">[$1]</span>');

    // Kasyrra name — special amber-purple
    html = html.replace(/\bKasyrra\b/g,
      '<span class="name-kasyrra">Kasyrra</span>');

    // Companion names → bold
    ['Saoirse', 'Mireille', 'Tierlan'].forEach(name => {
      html = html.replace(new RegExp(`\\b${name}\\b`, 'g'),
        `<strong>${name}</strong>`);
    });

    // Location names → italic teal
    ['Wolf-Road', 'Warming Frost', 'Imp Warren',
     'Kitsune Circuit', 'Cult Ascent'].forEach(loc => {
      html = html.replace(new RegExp(loc, 'g'),
        `<em class="location-name">${loc}</em>`);
    });

    return html;
  }

  // Keep _colorizeNarrative as an alias for backwards compat
  const _colorizeNarrative = postProcess;

  function _escapeHtml(str) {
    return str
      .replace(/&/g,  '&amp;')
      .replace(/</g,  '&lt;')
      .replace(/>/g,  '&gt;')
      .replace(/"/g,  '&quot;')
      .replace(/'/g,  '&#39;');
  }

  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  return { init, startStream, cancel, clear };

})();
