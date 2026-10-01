"""Testy robots.txt: reguły z wildcardami i parser stdlib."""

from __future__ import annotations

from evradar.robots import parse_wildcard_rules, wildcard_blocked

ROBOTS = """
User-agent: *
Allow: /samochody/uzywane/
Disallow: /*_page=
Disallow: */cart*
Disallow: *?*prefn1=*
Disallow: /panel/$

User-agent: Googlebot-Image
Disallow: /*.png
"""


def test_wildcard_rules() -> None:
    rules = parse_wildcard_rules(ROBOTS)
    assert wildcard_blocked(rules, "/lista?_page=2")
    assert wildcard_blocked(rules, "/pl-pl/cart")
    assert wildcard_blocked(rules, "/pl-pl/samochody?prefn1=fuel&prefv1=x")
    assert wildcard_blocked(rules, "/panel/")
    assert not wildcard_blocked(rules, "/panel/x")
    assert not wildcard_blocked(rules, "/pl-pl/samochody?start=0&sz=200")
    assert not wildcard_blocked(rules, "/obraz.png")  # reguła innej grupy User-agent
