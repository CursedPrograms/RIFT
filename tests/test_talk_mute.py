"""Fleet/talk_mute.py: every robot's two talk switches (sound, chat), delivered to the robots and learned back."""
from Fleet import conversations, talk_mute


class FakeRobots:
    """Each robot's /talkmute, answering like the firmware does (None: older firmware)."""

    def __init__(self, **robots):
        self.robots = {n: (None if v is None else dict(v)) for n, v in robots.items()}

    def __call__(self, url, payload=None, timeout=5):
        name = url.split("//")[1].split("/")[0].upper()
        r = self.robots.get(name)
        if r is None:
            return {"error": "not here"}          # a 404 page: no switch
        if "?" in url:
            for part in url.split("?", 1)[1].split("&"):
                k, v = part.split("=")
                r["talk_muted" if k == "on" else k] = v == "1"
        return dict(r)


def both(muted=False, chat_off=False):
    return {"talk_muted": muted, "chat_off": chat_off}


def fresh(tmp_path, monkeypatch, robots):
    monkeypatch.setattr(talk_mute, "PATH", str(tmp_path / "talk_mute.json"))
    monkeypatch.setattr(talk_mute, "_all", {"muted": False, "chat_off": False})
    for name in ("_state", "_want", "_checked"):
        monkeypatch.setattr(talk_mute, name, {})
    monkeypatch.setattr(talk_mute, "_no_switch", set())
    fake = FakeRobots(**robots)
    monkeypatch.setattr(conversations, "_request_json", fake)
    return fake, {n: f"http://{n.lower()}" for n in robots}


def test_two_switches_one_robot(tmp_path, monkeypatch):
    fake, urls = fresh(tmp_path, monkeypatch, {"NORA": both(), "WHIP": both()})
    talk_mute.sync(urls)
    talk_mute.set_switch("NORA", "muted", True)
    talk_mute.set_switch("WHIP", "chat_off", True)
    talk_mute.sync(urls)
    assert fake.robots["NORA"] == both(muted=True)
    assert fake.robots["WHIP"] == both(chat_off=True)
    assert talk_mute.muted("NORA") and not talk_mute.chat_off("NORA")
    assert talk_mute.chat_off("WHIP") and not talk_mute.muted("WHIP")


def test_robot_own_switch_wins(tmp_path, monkeypatch):
    fake, urls = fresh(tmp_path, monkeypatch, {"MILA": both()})
    talk_mute.sync(urls)
    fake.robots["MILA"]["chat_off"] = True        # flipped on her own page
    talk_mute._checked.clear()
    talk_mute.sync(urls)
    assert talk_mute.chat_off("MILA") and not talk_mute.muted("MILA")


def test_all_covers_newcomers(tmp_path, monkeypatch):
    fake, urls = fresh(tmp_path, monkeypatch, {"NORA": both()})
    talk_mute.sync(urls)
    talk_mute.set_all("muted", True)
    talk_mute.sync(urls)
    assert fake.robots["NORA"]["talk_muted"] is True
    fake.robots["FLORA"] = both()
    urls["FLORA"] = "http://flora"
    talk_mute.sync(urls)
    talk_mute.sync(urls)
    assert fake.robots["FLORA"] == both(muted=True)


def test_old_firmware_is_left_out_by_rift(tmp_path, monkeypatch):
    fake, urls = fresh(tmp_path, monkeypatch, {"IDA": None})
    talk_mute.set_switch("IDA", "chat_off", True)
    talk_mute.sync(urls)
    snap = talk_mute.snapshot()["robots"]["IDA"]
    assert snap["chat_off"] and not snap["pending"] and not snap["own_switch"]


def test_chirp_answers_are_learned(tmp_path, monkeypatch):
    fresh(tmp_path, monkeypatch, {"NORA": both(), "WHIP": both()})
    monkeypatch.setattr(conversations.time, "sleep", lambda s: None)
    urls = {"NORA": "http://nora", "WHIP": "http://whip"}
    monkeypatch.setattr(conversations, "_chirp", lambda url: "chat_off" if "nora" in url else True)
    assert conversations.converse("NORA", "WHIP", urls, phrase=0) is False
    assert talk_mute.chat_off("NORA")
    monkeypatch.setattr(conversations, "_chirp", lambda url: "silent" if "whip" in url else True)
    conversations.converse("WHIP", "NORA", urls, phrase=0)
    assert talk_mute.muted("WHIP")
    line = [e for e in conversations.snapshot()["log"] if e["from"] == "WHIP"][-1]
    assert line["ok"] and line["silent"]


def test_saved_across_restarts_and_old_file(tmp_path, monkeypatch):
    fake, urls = fresh(tmp_path, monkeypatch, {"AURA": both()})
    talk_mute.set_switch("AURA", "chat_off", True)
    talk_mute.sync(urls)
    talk_mute._state.clear()
    talk_mute._load()
    assert talk_mute._state["AURA"]["chat_off"] is True
    (tmp_path / "talk_mute.json").write_text('{"all": true, "robots": {"NORA": true}, "pending": {}}')
    talk_mute._state.clear()
    talk_mute._load()                              # the first file: one switch, sound
    assert talk_mute._all["muted"] is True and talk_mute._state["NORA"] == {"muted": True}
