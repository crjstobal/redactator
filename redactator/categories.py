"""What the user can tick, and which detectors each choice switches on.

Every category can be backed by up to three independent detectors, and their
results are merged. A miss by one is usually caught by another:
- rules:  fixed patterns (rules.py), always reliable for data with a known shape
- gliner: GLiNER2-PII, a small open model trained only to spot personal data
- gemma:  Gemma 4, which reads the text and judges what fits the description
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Category:
    id: str
    title: str
    rules: tuple[str, ...] = ()
    gliner: tuple[str, ...] = ()
    gemma: str = ""
    faces: bool = False
    default: bool = True


CATEGORIES: dict[str, Category] = {
    c.id: c
    for c in [
        Category("names", "Names", gliner=("person",), gemma="people's names"),
        Category("faces", "Faces", faces=True),
        Category("emails", "Emails", rules=("email",), gliner=("email",)),
        Category("phones", "Phone numbers", rules=("phone",), gliner=("phone_number",)),
        Category("addresses", "Addresses", gliner=("street_address", "address"), gemma="postal addresses (street, number, postcode)"),
        Category("birthdates", "Birth dates", gliner=("date_of_birth",), gemma="dates of birth"),
        Category(
            "ids",
            "ID numbers",
            rules=("us ssn",),
            gliner=("national_id_number", "passport_number", "drivers_license_number", "tax_id", "government_id"),
            gemma="ID document numbers (passport, national ID, driver's licence, tax ID)",
        ),
        Category(
            "money",
            "Card and bank details",
            rules=("credit card", "card expiry and cvv", "iban"),
            gliner=("card_number", "card_cvv", "bank_account", "iban", "routing_number"),
        ),
        Category(
            "secrets",
            "Passwords and API keys",
            rules=("secret", "password"),
            gliner=("password", "api_key", "access_token", "recovery_code"),
        ),
        Category("plates", "Licence plates", rules=("licence plate",), gemma="vehicle licence plates"),
        Category("companies", "Company names", gemma="names of companies and organisations", default=False),
        Category("web", "IP addresses and private links", rules=("ip address", "url with private data"), gliner=("ip_address",), default=False),
    ]
}

DEFAULT_HIDE = [c.id for c in CATEGORIES.values() if c.default]


@dataclass
class Options:
    hide: list[str] = field(default_factory=lambda: list(DEFAULT_HIDE))
    also: list[str] = field(default_factory=list)  # exact text, or a short description
    keep: list[str] = field(default_factory=list)  # never hide anything containing these

    @property
    def selected(self) -> list[Category]:
        return [CATEGORIES[c] for c in self.hide if c in CATEGORIES]

    @property
    def faces(self) -> bool:
        return any(c.faces for c in self.selected)

    @property
    def descriptions(self) -> list[str]:
        """Extra entries that read like a description ("my client's company") go to Gemma too."""
        return [a for a in self.also if len(a.split()) >= 2 and not any(ch.isdigit() for ch in a)]


def split_list(text: str) -> list[str]:
    """'9256YT, Acme Corp\\nmy client's company' -> ['9256YT', 'Acme Corp', "my client's company"]"""
    parts = [p.strip().strip("\"'“”") for chunk in (text or "").splitlines() for p in chunk.split(",")]
    return [p for p in parts if p]
