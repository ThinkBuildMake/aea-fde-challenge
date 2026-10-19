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

  async function post(url, body) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) throw new Error(url + ' ' + response.status);
    return response.json();
  }
  const startConversation = () => post('/conversations');
  const sendMessage = (id, text) => post('/conversations/' + id + '/messages', { text });
  const recordSolved = (id, answer) => post('/conversations/' + id + '/solved', { answer });

  let generation = 0;
  let conversation = startConversation();
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

  async function send(text) {
    if (!text || pending) return;
    const mine = generation;
    setBusy(true);
    chips.hidden = true;
    ended.hidden = true;
    solvedBar.hidden = true;
    addBubble('you', text);
    input.value = '';
    const typing = addTyping();
    try {
      const { conversationId } = await conversation;
      const result = await sendMessage(conversationId, text);
      if (mine !== generation) return;
      stopTyping(typing);
      addBubble('bot', result.text);
      solvedBar.hidden = !result.actions.includes('ask_solved');
    } catch (error) {
      if (mine !== generation) return;
      stopTyping(typing);
    } finally {
      if (mine === generation) setBusy(false);
    }
  }

  async function solved(answer) {
    const mine = generation;
    solvedBar.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    try {
      const { conversationId } = await conversation;
      const result = await recordSolved(conversationId, answer);
      if (mine !== generation) return;
      solvedBar.hidden = true;
      addBubble('bot', result.text);
      $('ended-text').textContent = ENDED_TEXT[result.status] || ENDED_TEXT.active;
      composer.hidden = result.status === 'ended';
      ended.hidden = false;
    } finally {
      solvedBar.querySelectorAll('button').forEach((b) => { b.disabled = false; });
    }
  }

  function newConversation() {
    generation += 1;
    clearTimeout(timer);
    timer = null;
    messages.replaceChildren();
    solvedBar.hidden = true;
    ended.hidden = true;
    chips.hidden = false;
    composer.hidden = false;
    input.value = '';
    setBusy(false);
    conversation = startConversation();
    const mine = generation;
    conversation.then((started) => {
      if (mine === generation) addBubble('bot', started.greeting);
    });
  }

  chips.addEventListener('click', (event) => {
    const chip = event.target.closest('.chip');
    if (chip) send(chip.dataset.text);
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
