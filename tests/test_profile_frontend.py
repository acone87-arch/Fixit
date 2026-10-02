from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_profile_is_available_to_every_role_and_persists_appearance():
    source = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    nav = source.split("const NAV = {", 1)[1].split("\n};", 1)[0]
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    assert "['profile', 'Профиль и настройки']" not in nav
    assert 'id="user-profile-btn"' in html
    assert "getElementById('user-profile-btn').addEventListener('click'" in source
    assert "[...(NAV[state.me?.role] || []).map(([key]) => key), 'profile']" in source
    assert "fixit-theme" in source and "fixit-text-size" in source
    assert "system" in source and "light" in source and "dark" in source
    assert "standard" in source and "large" in source and "xlarge" in source


def test_profile_has_loading_error_unsupported_denied_and_installed_states():
    source = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    for phrase in ("Проверяем установку", "Ошибка проверки", "Уведомления не поддерживаются", "Уведомления запрещены браузером", "Приложение установлено"):
        assert phrase in source
    assert "deferredInstallPrompt" in source and "isStandalone()" in source


def test_large_text_and_keyboard_accessibility_rules_are_present():
    styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
    assert 'data-text-size="xlarge"' in styles
    assert ":focus-visible" in styles
    assert "overflow-x:hidden" in styles
    assert "prefers-reduced-motion" in styles


def test_light_theme_covers_operational_cards_and_mobile_navigation():
    styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
    required_light_surfaces = (
        '.pulse-command',
        '.metric-card',
        '.mobile-info-card',
        '.pulse-panel',
        '.mobile-topbar',
        '.mobile-nav',
        '.tech-request-workspace',
        '.service-request-detail',
    )
    for selector in required_light_surfaces:
        assert f'html[data-theme="light"] {selector}' in styles
    assert "--light-text:#112038" in styles
    assert "--light-muted:#526A89" in styles
