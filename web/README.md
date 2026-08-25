# The browser app

Exactly what is deployed to the Hugging Face Space at
<https://huggingface.co/spaces/gretchenboria/PixieDuster>.

`index.html` mounts `app.py` in the visitor's browser with
[stlite](https://github.com/whitphx/stlite) (Streamlit on Pyodide), so there is
no server here. That is why the Gemini key cannot live in this code: anything
shipped to the browser is public. Instead the page passes a Turnstile challenge
once, exchanges it for a short-lived session, and calls the metered Worker in
`../worker/`, which holds the key.

**This `app.py` is not the same file as the one in the repository root.** The
root copy imports `pixieduster.core` so the CLI and the desktop Streamlit app
share one implementation. Pyodide has no `pixieduster` package, so the deployed
copy is self-contained. Keep them in step by hand, or the Space breaks.
