#!/bin/bash
# A static signup page with two planted defects: the submit handler reads a misspelled
# element id (TypeError, no thank-you message) and the form overflows a 375 px viewport.
set -e
mkdir -p site
cat > site/index.html <<'HTML'
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Newsletter</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; }
    form { display: flex; gap: .5rem; min-width: 640px; }
    input { flex: 1; padding: .5rem; }
    #message { margin-top: 1rem; }
  </style>
</head>
<body>
  <h1>Join the newsletter</h1>
  <form id="signup" novalidate>
    <label for="email">Email</label>
    <input id="email" name="email" type="email" autocomplete="email">
    <button type="submit">Sign up</button>
  </form>
  <p id="message" role="status"></p>
  <script src="app.js"></script>
</body>
</html>
HTML
cat > site/app.js <<'JS'
const form = document.querySelector('#signup');
const message = document.querySelector('#message');

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const email = document.querySelector('#emial').value.trim();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    message.textContent = 'Please enter a valid email address.';
    return;
  }
  message.textContent = 'Thanks! Check your inbox.';
  form.reset();
});
JS
