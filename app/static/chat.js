(() => {
  const $ = (id) => document.getElementById(id);
  const messages = $('messages');
  const chips = $('chips');
  const composer = $('composer');
  const input = $('msg');
  const sendButton = composer.querySelector('button');
  const solvedBar = $('solved-bar');
  const ended = $('ended');
  const STILL_WORKING_MS = 10000;
  const ENDED_TEXT = {
    ended: 'Thanks, your answer is saved. This conversation has ended.',
    active: 'Thanks. We recorded that this did not solve it. Reply below if you want a person.',
  };
  const HANDED_OVER = 'This conversation has been handed over.';
  const STATUS_ENDED_TEXT = {
    handed_off: HANDED_OVER,
    safety_stop: 'This conversation has ended.',
    ended: 'This conversation has ended.',
  };
  const BANNERS = {
    handoff: ['Passed to a person', 'warn'],
    safety_stop: ['Safety stop. Leave the home and call 911.', 'stop'],
    error: ['Something went wrong on our side', 'warn'],
  };
  const CHOICES_LABEL = 'Open windows in your area';
  const CARD_TITLE = 'Visit booked';
  const WAIVED_LINE = 'Diagnostic fee waived for members';
  const WAITLIST_LINE = 'On the waitlist for an earlier window. The team will call you if one opens.';
  const PICKER_TITLE = 'When is the best time for the call back?';
  const PICKER_NOTE = 'The person who calls will already have this conversation, so you will not need to repeat it.';
  const WINDOWS = [['morning', 'Morning'], ['afternoon', 'Afternoon'], ['evening', 'Evening']];
  const OUTAGE_LABEL = 'Simulate an outage';
  const OUTAGE_TEXT = 'Can I move my visit?';
  const SEND_FAILED = 'That did not go through. Please try again.';
  const TURN_CAP_TEXT = 'This conversation has reached its limit. Please start a new conversation, or ask for a call back.';
  const PICK_FAILED = 'That did not go through. Please pick a time again.';
  const banner = $('chat-banner');
  const GREETING = messages.querySelector('.bubble.bot').textContent;

  async function post(url, body) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      const error = new Error(url + ' ' + response.status);
      error.status = response.status;
      error.code = await response.json().then((body) => body.error, () => undefined);
      throw error;
    }
    return response.json();
  }
  const startConversation = () => post('/conversations');
  const sendMessage = (id, text, simulateOutage) => post(
    '/conversations/' + id + '/messages',
    simulateOutage ? { text, simulateOutage: true } : { text },
  );
  const recordSolved = (id, answer) => post('/conversations/' + id + '/solved', { answer });
  const submitCallbackWindow = (id, window) => post('/conversations/' + id + '/callback-window', { window });

  let generation = 0;
  let conversation = begin();
  let pending = false;
  let timer = null;

  function addBubble(who, text) {
    const row = document.createElement('div');
    row.className = 'msg-row ' + who;
    const bubble = document.createElement('div');
    bubble.className = 'bubble ' + who;
    bubble.textContent = text;
    row.appendChild(bubble);
    messages.appendChild(row);
    return row;
  }

  function begin() {
    const mine = generation;
    const started = startConversation();
    started.then((s) => { if (mine === generation) setOutageChip(s.demoFaults); }, () => {});
    return started;
  }

  async function currentConversation() {
    const current = conversation;
    try {
      return await current;
    } catch {
      if (conversation === current) conversation = begin();
      return conversation;
    }
  }

  function setOutageChip(on) {
    chips.querySelector('#outage-chip')?.remove();
    if (!on) return;
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.id = 'outage-chip';
    chip.className = 'chip';
    chip.textContent = OUTAGE_LABEL;
    chips.appendChild(chip);
  }

  function setBanner(kind) {
    const shown = BANNERS[kind];
    banner.hidden = !shown;
    banner.className = 'chat-banner' + (shown ? ' ' + shown[1] : '');
    banner.textContent = shown ? shown[0] : '';
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function hour(value) {
    const h = Number(value.split(':')[0]);
    return (h % 12 || 12) + (h < 12 ? ' AM' : ' PM');
  }

  function formatDay(isoDate) {
    const [y, m, d] = isoDate.split('-').map(Number);
    const day = new Date(Date.UTC(y, m - 1, d));
    const part = (options) => day.toLocaleDateString('en-US', { timeZone: 'UTC', ...options });
    return part({ weekday: 'long' }) + ' ' + part({ month: 'long' }) + ' ' + d;
  }

  function addChoices(list) {
    const block = el('div', 'choices');
    block.appendChild(el('div', 'choices-label', CHOICES_LABEL));
    for (const choice of list) {
      const button = el('button', 'choice', choice.label);
      button.type = 'button';
      button.addEventListener('click', () => send(choice.text));
      block.appendChild(button);
    }
    messages.appendChild(block);
  }

  function addBookingCard(booking, waitlisted) {
    const card = el('div', 'booking-card');
    const [start, end] = booking.window.split('-');
    card.appendChild(el('div', 'booking-title', CARD_TITLE));
    card.appendChild(el('div', '', formatDay(booking.date) + ', ' + hour(start) + ' to ' + hour(end)));
    card.appendChild(el('div', '', 'Technician ' + booking.technicianName));
    const cents = booking.diagnosticFeeCents;
    if (cents !== null && !booking.diagnosticFeeWaived) {
      const dollars = cents % 100 ? (cents / 100).toFixed(2) : String(cents / 100);
      card.appendChild(el('div', '', 'Diagnostic fee $' + dollars + ', credited toward the repair'));
    } else if (booking.diagnosticFeeWaived) {
      card.appendChild(el('div', '', WAIVED_LINE));
    }
    if (waitlisted) card.appendChild(el('div', 'waitlist-line', WAITLIST_LINE));
    messages.appendChild(card);
  }

  function addCallbackPicker() {
    const picker = el('div', 'callback-picker');
    picker.appendChild(el('div', 'callback-title', PICKER_TITLE));
    const options = el('div', 'callback-options');
    for (const [value, label] of WINDOWS) {
      const button = el('button', 'btn btn-outline', label);
      button.type = 'button';
      button.addEventListener('click', () => pickWindow(value, picker));
      options.appendChild(button);
    }
    picker.appendChild(options);
    picker.appendChild(el('div', 'callback-note', PICKER_NOTE));
    messages.appendChild(picker);
  }

  function showEnded(text) {
    composer.hidden = true;
    chips.hidden = true;
    $('ended-text').textContent = text;
    ended.hidden = false;
  }

  function removeAll(selector) {
    messages.querySelectorAll(selector).forEach((node) => node.remove());
  }

  function renderReply(result) {
    removeAll('.choices, .callback-picker');
    setBanner(result.banner);
    addBubble('bot', result.text);
    if (result.choices.length) addChoices(result.choices);
    if (result.booking) addBookingCard(result.booking, result.waitlisted);
    const actions = result.actions;
    if (actions.includes('choose_callback_window') || actions.includes('request_callback')) {
      addCallbackPicker();
    }
    solvedBar.hidden = !actions.includes('ask_solved');
    composer.hidden = actions.includes('choices_only');
    if (STATUS_ENDED_TEXT[result.status]) showEnded(STATUS_ENDED_TEXT[result.status]);
  }

  async function pickWindow(window, picker) {
    const mine = generation;
    const buttons = picker.querySelectorAll('button');
    buttons.forEach((b) => { b.disabled = true; });
    try {
      const { conversationId } = await currentConversation();
      if (mine !== generation) return;
      const result = await submitCallbackWindow(conversationId, window);
      if (mine !== generation) return;
      addBubble('bot', result.text);
      showEnded(HANDED_OVER);
    } catch {
      if (mine !== generation) return;
      buttons.forEach((b) => { b.disabled = false; });
      picker.querySelector('.send-error')?.remove();
      picker.appendChild(el('div', 'send-error', PICK_FAILED));
    }
  }

  function addTyping() {
    const row = addBubble('bot', 'Looking that up...');
    row.firstChild.className = 'bubble typing';
    const note = document.createElement('div');
    note.id = 'still-working';
    note.className = 'still-working';
    note.hidden = true;
    note.textContent = 'Still working on it. Thanks for waiting.';
    row.firstChild.after(note);
    row.classList.add('typing-row');
    timer = setTimeout(() => { note.hidden = false; }, STILL_WORKING_MS);
    return row;
  }

  function stopTyping(row) {
    clearTimeout(timer);
    timer = null;
    row.remove();
  }

  function setBusy(busy) {
    pending = busy;
    sendButton.disabled = busy;
  }

  async function send(text, simulateOutage = false) {
    if (!text || pending) return;
    removeAll('.send-error');
    const mine = generation;
    setBusy(true);
    chips.hidden = true;
    ended.hidden = true;
    solvedBar.hidden = true;
    addBubble('you', text);
    input.value = '';
    const typing = addTyping();
    try {
      const { conversationId } = await currentConversation();
      if (mine !== generation) return;
      const result = await sendMessage(conversationId, text, simulateOutage);
      if (mine !== generation) return;
      stopTyping(typing);
      renderReply(result);
    } catch (error) {
      if (mine !== generation) return;
      stopTyping(typing);
      if (error.code === 'turn_limit_reached') addBubble('bot', TURN_CAP_TEXT);
      if (error.code === 'turn_limit_reached' || error.code === 'conversation_ended') {
        showEnded(STATUS_ENDED_TEXT.ended);
      } else {
        messages.appendChild(el('div', 'send-error', SEND_FAILED));
      }
    } finally {
      if (mine === generation) setBusy(false);
    }
  }

  async function solved(answer) {
    const mine = generation;
    solvedBar.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    try {
      const { conversationId } = await currentConversation();
      if (mine !== generation) return;
      const result = await recordSolved(conversationId, answer);
      if (mine !== generation) return;
      solvedBar.hidden = true;
      addBubble('bot', result.text);
      $('ended-text').textContent = ENDED_TEXT[result.status] || ENDED_TEXT.active;
      composer.hidden = result.status === 'ended';
      ended.hidden = false;
    } catch (error) {
      if (mine === generation && error.status === 409) solvedBar.hidden = true;
    } finally {
      solvedBar.querySelectorAll('button').forEach((b) => { b.disabled = false; });
    }
  }

  function newConversation() {
    generation += 1;
    clearTimeout(timer);
    timer = null;
    messages.replaceChildren();
    addBubble('bot', GREETING);
    setBanner('none');
    setOutageChip(false);
    solvedBar.hidden = true;
    ended.hidden = true;
    chips.hidden = false;
    composer.hidden = false;
    input.value = '';
    setBusy(false);
    conversation = begin();
  }

  chips.addEventListener('click', (event) => {
    const chip = event.target.closest('.chip');
    if (chip?.id === 'outage-chip') send(OUTAGE_TEXT, true);
    else if (chip) send(chip.dataset.text);
  });
  composer.addEventListener('submit', (event) => {
    event.preventDefault();
    send(input.value.trim());
  });
  $('solved-yes').addEventListener('click', () => solved('yes'));
  $('solved-no').addEventListener('click', () => solved('no'));
  $('new-conversation').addEventListener('click', newConversation);
  $('start-new').addEventListener('click', newConversation);
})();
