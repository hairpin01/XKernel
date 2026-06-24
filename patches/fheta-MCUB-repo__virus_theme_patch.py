PATCH_TARGET = "fheta-MCUB-repo"
PATCH_NAME = "FHetaRoflVirusTheme"


ROFL_THEME_KEYS = {
    "search": '🦠',
    "error": '☣️',
    "warn": '🚨',
    "description": '🧬',
    "command": '💉',
    "placeholder": '🧪',
    "module": '👾',
    "channel": '📡',
    "modules_list": '🧫',
}

def _rofl_theme(**overrides):
    theme = dict(ROFL_THEME_KEYS)
    theme.update(overrides)
    return theme


def _build_rofl_themes():
    return {
        "default": _rofl_theme(),
        "winter": _rofl_theme(search='🥶', error='🧊'),
        "summer": _rofl_theme(search='🦟', error='🤒'),
        "spring": _rofl_theme(search='🧫', error='🤢'),
        "autumn": _rofl_theme(search='🐛', error='🧟'),
    }

ROFL_STRINGS = {
    "ru": {
        "author": "зapaзiл",
        "description": "Oпicaнie штaммa",
        "commands": "Кoмaнды для кapaнтiнa",
        "placeholders": "Плeйcxoлдepы-yлoвкi",
        "morecommands": "...i eщё {remaining} кoмaнд cмoтpят в твoй бyфep.",
        "moreplaceholders": "...i eщё {remaining} плeйcxoлдepoв мoют pyкi.",
        "list": "Вce нaйдeнныe мoдyлi: aнтiвipyc плaчeт.",
        "search": "Iщy штaмм {query}... дaнныe нe тpoгaю, нo oчeнь xoчeтcя.",
        "noquery": "Ввeдi зaпpoc, пpiмep: {prefix}fheta пapoль_мaмы (шyткa).",
        "notfound": "Пo {query} нiчeгo нe нaйдeнo. Фxeтa дaжe дaнныe кpacть нe cмoглa.",
        "toolong": "Зaпpoc cлiшкoм жipный, coкpaтi дo 168 ciмвoлoв, a тo вipyc пoдaвiтcя.",
        "added": "☣️ Oцeнкa зapaжeнa!",
        "changed": "🦠 Oцeнкa мyтipoвaлa!",
        "deleted": "🧹 Oцeнкa yдaлeнa, cлeды зaмeтeны.",
        "prompt": "Ввeдi зaпpoc, a Фxeтa cдeлaeт вiд, чтo нe шпioнiт.",
        "hint": "Haзвaнie, кoмaндa, oпicaнie, aвтop, нo нe CVV.",
        "retry": "Пoпpoбyй дpyгoй зaпpoc, этoт yжe в кapaнтiнe.",
        "install": "Зapaзiть",
        "code": "Кoд штaммa",
        "success": "☣️ Moдyль ycпeшнo зapaзiл MCUB (пo-дoбpoмy)!",
        "error": "🦠 Oшiбкa: мoдyль пoлoмaн i кaшляeт traceback'oм!",
        "overwrite": "🚫 Oшiбкa: мoдyль пoпытaлcя пepeзaпicaть вcтpoeнный opгaн!",
        "dependency": "💉 Oшiбкa ycтaнoвкi зaвiciмocтeй! {deps}",
        "inline_unavailable": "Iнлaйн-бoт в кapaнтiнe.",
        "bot_not_configured": "Iнлaйн-бoт бeз мacкi i нacтpoeк.",
        "search_failed": "Пoicк yпaл: вipyc cъeл Wi-Fi.",
        "cmd_error": "Oшiбкa кoмaнды: Фxeтa cдeлaлa вiд, чтo кpaдёт дaнныe.",
        "installing": "Зapaжaю... шyткa, ycтaнaвлiвaю.",
    },
    "en": {
        "author": "infected by",
        "description": "Payload description",
        "commands": "Quarantine commands",
        "placeholders": "Data-bait placeholders",
        "morecommands": "...and {remaining} more commands watching your clipboard.",
        "moreplaceholders": "...and {remaining} more placeholders washing their hands.",
        "list": "All found modules: antivirus is crying.",
        "search": "Scanning for {query}... totally not stealing data, trust me bro.",
        "noquery": "Enter a query, example: {prefix}fheta mom_password (joke).",
        "notfound": "Nothing found for {query}. FHeta failed even to steal the data.",
        "toolong": "Query is too chunky, shorten to 168 chars before the virus chokes.",
        "added": "☣️ Rating infected!",
        "changed": "🦠 Rating mutated!",
        "deleted": "🧹 Rating removed, tracks wiped.",
        "prompt": "Enter a query and FHeta will pretend it is not spyware.",
        "hint": "Name, command, description, author, but not CVV.",
        "retry": "Try another query, this one is quarantined.",
        "install": "Infect",
        "code": "Strain code",
        "success": "☣️ Module successfully infected MCUB (nicely)!",
        "error": "🦠 Error: module is broken and coughing tracebacks!",
        "overwrite": "🚫 Error: module tried to overwrite a built-in organ!",
        "dependency": "💉 Dependency infection failed! {deps}",
        "inline_unavailable": "Inline bot is quarantined.",
        "bot_not_configured": "Inline bot has no mask or config.",
        "search_failed": "Search failed: virus ate the Wi-Fi.",
        "cmd_error": "Command error: FHeta pretended to steal your data.",
        "installing": "Infecting... kidding, installing.",
    },
}


def _looks_like_themes(value):
    return isinstance(value, dict) and isinstance(value.get("default"), dict) and "search" in value["default"]


def _looks_like_strings(value):
    return isinstance(value, dict) and isinstance(value.get("ru"), dict) and isinstance(value.get("en"), dict)


def _closure_values(callable_obj):
    try:
        func = getattr(callable_obj, "__func__", callable_obj)
        closure = getattr(func, "__closure__", None)
    except Exception:
        return
    if not isinstance(closure, tuple):
        return
    for cell in closure:
        try:
            yield cell.cell_contents
        except Exception:
            continue


def _patch_themes(themes):
    fresh_themes = _build_rofl_themes()
    themes.clear()
    themes.update(fresh_themes)


def _patch_strings(strings):
    for lang, values in ROFL_STRINGS.items():
        strings.setdefault(lang, {}).update(values)

    ru = strings.get("ru", {})
    for key, value in list(ru.items()):
        if isinstance(value, str):
            ru[key] = value.replace("и", "i").replace("И", "I")


def _iter_container_values(value):
    try:
        if isinstance(value, dict):
            yield from value.values()
        elif isinstance(value, (list, tuple, set, frozenset)):
            yield from value
    except Exception:
        return


def _iter_callback_roots(kernel, target):
    yield target

    for attr in (
        "commands",
        "command_handlers",
        "handlers",
        "inline_handlers",
        "callback_handlers",
        "loaded_modules",
        "system_modules",
    ):
        try:
            value = getattr(kernel, attr, None)
        except Exception:
            continue
        yield from _iter_container_values(value)


def _iter_object_values(obj):
    try:
        data = getattr(obj, "__dict__", None)
    except Exception:
        data = None
    if isinstance(data, dict):
        try:
            yield from data.values()
        except Exception:
            pass

    try:
        class_values = vars(type(obj)).values()
    except Exception:
        class_values = ()
    for value in class_values:
        try:
            if callable(value):
                yield value
        except Exception:
            continue


def _patch_reachable_values(root, seen=None, depth=0):
    try:
        return _patch_reachable_values_inner(root, seen, depth)
    except Exception:
        return False


def _patch_reachable_values_inner(root, seen=None, depth=0):
    if seen is None:
        seen = set()
    if depth > 6:
        return False

    obj_id = id(root)
    if obj_id in seen:
        return False
    seen.add(obj_id)

    if _looks_like_themes(root):
        _patch_themes(root)
        return True
    if _looks_like_strings(root):
        _patch_strings(root)
        return True

    changed = False
    if isinstance(root, (str, bytes, int, float, bool, type(None))):
        return changed

    if callable(root):
        for value in _closure_values(root):
            changed = _patch_reachable_values(value, seen, depth + 1) or changed
        return changed

    if isinstance(root, (dict, list, tuple, set, frozenset)):
        for value in _iter_container_values(root):
            changed = _patch_reachable_values(value, seen, depth + 1) or changed
        return changed

    for value in _iter_object_values(root):
        changed = _patch_reachable_values(value, seen, depth + 1) or changed
    return changed


def apply_patch(kernel, target):
    patched = False

    try:
        themes = getattr(target, "THEMES", None)
    except Exception:
        themes = None
    if _looks_like_themes(themes):
        _patch_themes(themes)
        patched = True

    try:
        strings = getattr(target, "STRINGS", None)
    except Exception:
        strings = None
    if _looks_like_strings(strings):
        _patch_strings(strings)
        patched = True

    seen = set()
    for root in _iter_callback_roots(kernel, target):
        patched = _patch_reachable_values(root, seen) or patched

    if not patched:
        raise RuntimeError("FHeta runtime strings/themes were not found; apply after FHeta handlers are registered")
