from redactator import rules


def labels(text, enabled=None):
    return [(m.label, m.text) for m in rules.find(text, enabled or list(rules.RULES))]


def test_email_and_phone():
    found = labels("Email: maria.lopez@acme-corp.com  Phone: +34 612 345 678")
    assert ("email", "maria.lopez@acme-corp.com") in found
    assert ("phone", "+34 612 345 678") in found


def test_card_needs_valid_luhn():
    assert ("credit card", "4111 1111 1111 1111") in labels("VISA 4111 1111 1111 1111")
    assert not any(l == "credit card" for l, _ in labels("ref 4111 1111 1111 1112"))


def test_iban():
    assert ("iban", "ES91 2100 0418 4502 0005 1332") in labels("IBAN: ES91 2100 0418 4502 0005 1332")


def test_short_numbers_are_not_phones():
    assert labels("Total 1,350.00 EUR, order #48213") == []


def test_secret_tokens():
    found = labels("export OPENAI_KEY=sk-abcdefghijklmnopqrstuvwx")
    assert any(l == "secret" for l, _ in found)


def test_only_enabled_rules_run():
    assert labels("a@b.co +34 612 345 678", ["email"]) == [("email", "a@b.co")]
