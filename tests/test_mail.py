"""Mail, read straight from Gmail rather than through the connector.

Every test names the mutation that makes it fail. The network is never touched:
what is worth testing here is the reduction of Gmail's payloads to what a screen
can render, and that is pure.
"""

from __future__ import annotations

import base64
import json

import pytest

from psok.mail import gmail


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_the_body_prefers_the_plain_part_however_deeply_it_is_nested():
    """Gmail nests parts arbitrarily -- an `alternative` inside a `mixed` inside
    a `related` is ordinary mail, not a corner case -- so checking the first two
    levels finds the body of some messages and not others.

    Mutation check: stop recursing into `parts` in `_body_of`.
    """
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/related",
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [
                            {"mimeType": "text/plain", "body": {"data": _b64("the real body")}},
                            {"mimeType": "text/html", "body": {"data": _b64("<p>markup</p>")}},
                        ],
                    }
                ],
            }
        ],
    }
    body, from_html = gmail._body_of(payload)
    assert body == "the real body"
    assert from_html is False, "a plain part was there, so nothing was reduced"


def test_an_html_only_message_is_reduced_to_text_not_rendered():
    """An inbox is the most hostile input this system has. The view never gets
    markup to render: the server reduces it, and says that it did so the mangled
    layout reads as a choice rather than as a bug.

    Mutation check: return the HTML unchanged from `_body_of`.
    """
    html = (
        "<html><head><style>p{color:red}</style><title>t</title></head>"
        "<body><p>Hi Bilal,</p><p>Applications close &amp; soon</p>"
        "<script>alert(1)</script></body></html>"
    )
    body, from_html = gmail._body_of(
        {"mimeType": "text/html", "body": {"data": _b64(html)}}
    )
    assert from_html is True
    assert "<" not in body and ">" not in body
    assert "alert(1)" not in body, "a script's contents are not the message"
    assert "color:red" not in body
    assert "Applications close & soon" in body, "entities are unescaped"
    assert body.startswith("Hi Bilal,")


def test_preheader_padding_does_not_become_the_message():
    """Marketing mail pads its preheader with hundreds of zero-width joiners so
    the preview line is not filled by the body. Stripped naively they survive as
    invisible characters separated by spaces, and the first screen of the
    message is fifty lines of nothing -- which is what the real inbox this was
    written against produced.

    Mutation check: drop `_INVISIBLE` from `_html_to_text`.
    """
    padded = "<div>Apply Now!" + ("&#847;&zwnj;&#8203; " * 40) + "</div><p>Hi Bilal,</p>"
    body, _ = gmail._body_of({"mimeType": "text/html", "body": {"data": _b64(padded)}})
    assert body.startswith("Apply Now!")
    assert "Hi Bilal," in body
    assert len(body) < 60, f"padding survived: {body!r}"


def test_a_summary_carries_what_a_row_needs_and_reads_unread_from_labels():
    """`UNREAD` and `STARRED` are labels, not fields, and the categories Gmail
    files mail under (`CATEGORY_PROMOTIONS`) are noise in a row.

    Mutation check: return `labelIds` verbatim as `labels`.
    """
    message = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "a preview",
        "labelIds": ["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"],
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Final Hours"},
                {"name": "From", "value": "Priya <noreply@unstop.news>"},
                {"name": "Date", "value": "Sat, 29 Aug 2026 15:36:43 +0530"},
            ]
        },
    }
    row = gmail._summarise(message)
    assert row["subject"] == "Final Hours"
    assert row["from"] == "Priya <noreply@unstop.news>"
    assert row["unread"] is True and row["starred"] is False
    assert row["labels"] == ["INBOX", "UNREAD"], "categories are not labels a person set"


def test_a_message_with_no_subject_still_has_something_to_show():
    """Mutation check: return the empty string from `_summarise`."""
    assert gmail._summarise({"id": "m", "payload": {}})["subject"] == "(no subject)"


def test_accounts_ignores_a_file_written_before_a_sign_in_finished(tmp_path, monkeypatch):
    """The credentials directory holds more than accounts: an abandoned flow
    leaves `oauth_states.json`, and a half-written file has no refresh token.
    Counting either as an account is what made a connector nobody had signed in
    to report itself signed in.

    Mutation check: drop the `refresh_token` check from `accounts`.
    """
    monkeypatch.setattr(gmail, "CREDENTIALS_DIR", tmp_path)
    (tmp_path / "oauth_states.json").write_text("{}")
    (tmp_path / "half@gmail.com.json").write_text(json.dumps({"client_id": "x"}))
    (tmp_path / "real@gmail.com.json").write_text(
        json.dumps({"refresh_token": "r", "client_id": "c", "scopes": ["gmail.readonly"]})
    )

    found = gmail.accounts()
    assert [a.address for a in found] == ["real@gmail.com"]
    assert found[0].can_send is False, "a read-only grant cannot send, and says so"


def test_no_account_is_a_sentence_not_a_crash(tmp_path, monkeypatch):
    """The screen shows this text, so it has to name the thing to press.

    Mutation check: raise a bare RuntimeError from `_preferred`.
    """
    monkeypatch.setattr(gmail, "CREDENTIALS_DIR", tmp_path)
    with pytest.raises(gmail.MailUnavailable, match="Connectors"):
        gmail._preferred()
