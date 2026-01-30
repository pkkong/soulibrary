def provider_from_platforms(platforms):
    for code in platforms:
        if code in {"Kyobo", "Kyobo_New"}:
            return "교보"
        if code == "YES24":
            return "YES24"
        if code == "Aladin":
            return "알라딘"
        if code == "Bookcube":
            return "북큐브"
    return "기타"


def platform_to_provider_label(platform_code: str) -> str:
    if not platform_code:
        return "기타"
    code = str(platform_code)
    if code in {"Kyobo", "Kyobo_New"}:
        return "교보"
    if code == "YES24":
        return "YES24"
    if code == "Bookcube":
        return "북큐브"
    if code == "Aladin":
        return "알라딘"
    return "기타"
