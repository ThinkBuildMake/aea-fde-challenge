"""Eval records keep the payment link but never its token, so committed runs stay scan-clean."""

from app.evals.runner import redact_link_tokens


def test_payment_link_token_is_removed():
    text = "Pay here: https://pay.example.com/invoice/INV-204411?token=demo-token. Valid 24 hours."
    assert redact_link_tokens(text) == (
        "Pay here: https://pay.example.com/invoice/INV-204411?token=[removed]. Valid 24 hours."
    )


def test_text_without_a_link_is_unchanged():
    assert redact_link_tokens("No link here, token=abc") == "No link here, token=abc"
