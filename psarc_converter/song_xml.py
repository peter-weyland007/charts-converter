from __future__ import annotations

import bisect
import json
import os
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util import Counter

from .runtime import bundled_path, find_command


@dataclass
class Note:
    time: float
    string: int
    fret: int
    sustain: float = 0.0
    slide_to: int = -1
    slide_unpitch_to: int = -1
    bend: float = 0.0
    hammer_on: bool = False
    pull_off: bool = False
    harmonic: bool = False
    harmonic_pinch: bool = False
    palm_mute: bool = False
    mute: bool = False
    vibrato: bool = False
    tremolo: bool = False
    accent: bool = False
    link_next: bool = False
    tap: bool = False


@dataclass
class ChordTemplate:
    name: str
    fingers: list[int]
    frets: list[int]
    display_name: str = ""
    arpeggio: bool = False


@dataclass
class Chord:
    time: float
    chord_id: int
    notes: list[Note] = field(default_factory=list)
    high_density: bool = False


@dataclass
class Anchor:
    time: float
    fret: int
    width: int = 4


@dataclass
class Beat:
    time: float
    measure: int


@dataclass
class Section:
    name: str
    number: int
    start_time: float


@dataclass
class HandShape:
    chord_id: int
    start_time: float
    end_time: float
    arpeggio: bool = False


@dataclass
class Arrangement:
    name: str
    tuning: list[int] = field(default_factory=lambda: [0] * 6)
    capo: int = 0
    notes: list[Note] = field(default_factory=list)
    chords: list[Chord] = field(default_factory=list)
    anchors: list[Anchor] = field(default_factory=list)
    hand_shapes: list[HandShape] = field(default_factory=list)
    chord_templates: list[ChordTemplate] = field(default_factory=list)


@dataclass
class Song:
    title: str = ""
    artist: str = ""
    album: str = ""
    year: int = 0
    song_length: float = 0.0
    offset: float = 0.0
    beats: list[Beat] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    arrangements: list[Arrangement] = field(default_factory=list)


_FALSE_LITERALS = frozenset({"", "0", "false", "False", "FALSE"})
_PC_KEY = bytes.fromhex("CB648DF3D12A16BF71701414E69619EC171CCA5D2A142E3E59DE7ADDA18A3A30")
_MAC_KEY = bytes.fromhex("9821330E34B91F70D0A48CBD625993126970CEA09192C0E6CDA676CC9838289D")


def note_to_wire(n: Note) -> dict:
    return {
        "t": round(n.time, 3), "s": n.string, "f": n.fret,
        "sus": round(n.sustain, 3),
        "sl": n.slide_to, "slu": n.slide_unpitch_to,
        "bn": round(n.bend, 1) if n.bend else 0,
        "ho": n.hammer_on, "po": n.pull_off,
        "hm": n.harmonic, "hp": n.harmonic_pinch,
        "pm": n.palm_mute, "mt": n.mute,
        "vb": n.vibrato, "tr": n.tremolo,
        "ac": n.accent, "tp": n.tap,
    }


def chord_note_to_wire(cn: Note) -> dict:
    d = note_to_wire(cn)
    d.pop("t", None)
    return d


def chord_to_wire(c: Chord) -> dict:
    return {
        "t": round(c.time, 3),
        "id": c.chord_id,
        "hd": c.high_density,
        "notes": [chord_note_to_wire(cn) for cn in c.notes],
    }


def arrangement_to_wire(arr: Arrangement) -> dict:
    return {
        "name": arr.name,
        "tuning": list(arr.tuning),
        "capo": arr.capo,
        "notes": [note_to_wire(n) for n in arr.notes],
        "chords": [chord_to_wire(c) for c in arr.chords],
        "anchors": [{"time": a.time, "fret": a.fret, "width": a.width} for a in arr.anchors],
        "handshapes": [
            {"chord_id": h.chord_id, "start_time": h.start_time, "end_time": h.end_time, "arp": h.arpeggio}
            for h in arr.hand_shapes
        ],
        "templates": [
            {
                "name": ct.name,
                "displayName": ct.display_name or ct.name,
                "arp": ct.arpeggio,
                "fingers": list(ct.fingers),
                "frets": list(ct.frets),
            }
            for ct in arr.chord_templates
        ],
    }


def _float(elem, attr, default=0.0):
    v = elem.get(attr)
    return float(v) if v is not None else default


def _int(elem, attr, default=0):
    v = elem.get(attr)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return int(float(v))


def _bool(elem, attr):
    v = elem.get(attr)
    return v is not None and v not in _FALSE_LITERALS


def _parse_note(n) -> Note:
    return Note(
        time=_float(n, "time"),
        string=_int(n, "string"),
        fret=_int(n, "fret"),
        sustain=_float(n, "sustain"),
        slide_to=_int(n, "slideTo", -1),
        slide_unpitch_to=_int(n, "slideUnpitchTo", -1),
        bend=_float(n, "bend"),
        hammer_on=_bool(n, "hammerOn"),
        pull_off=_bool(n, "pullOff"),
        harmonic=_bool(n, "harmonic"),
        harmonic_pinch=_bool(n, "harmonicPinch"),
        palm_mute=_bool(n, "palmMute"),
        mute=_bool(n, "mute"),
        vibrato=_bool(n, "vibrato"),
        tremolo=_bool(n, "tremolo"),
        accent=_bool(n, "accent"),
        link_next=_bool(n, "linkNext"),
        tap=_bool(n, "tap"),
    )


def _detect_platform(extracted_dir: str | Path) -> str:
    parts = str(extracted_dir).lower()
    return "mac" if "/macos/" in parts or "/mac/" in parts else "pc"


def _find_rscli() -> str | None:
    env = os.environ.get("RSCLI_PATH", "")
    candidates = [
        env,
        str(bundled_path("tools", "rscli", "RsCli")),
        "/opt/rscli/RsCli",
        find_command("RsCli"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _convert_sng_to_xml(extracted_dir: str | Path) -> None:
    d = Path(extracted_dir)
    xml_files = list(d.rglob("*.xml"))
    has_arrangement_xml = False
    for xf in xml_files:
        try:
            root = ET.parse(xf).getroot()
        except Exception:
            continue
        if root.tag == "song":
            arr = (root.findtext("arrangement", default="") or "").lower().strip()
            if arr not in ("vocals", "showlights", "jvocals"):
                has_arrangement_xml = True
                break
    if has_arrangement_xml:
        return
    sng_files = list(d.rglob("*.sng"))
    if not sng_files:
        return
    rscli = _find_rscli()
    if not rscli:
        return
    platform = _detect_platform(d)
    arr_dir = d / "songs" / "arr"
    arr_dir.mkdir(parents=True, exist_ok=True)
    for sng_path in sng_files:
        if "vocals" in sng_path.stem.lower():
            continue
        xml_out = arr_dir / f"{sng_path.stem}.xml"
        if xml_out.exists():
            continue
        result = subprocess.run([rscli, "sng2xml", str(sng_path), str(xml_out), platform], capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(f"RsCli sng2xml failed for {sng_path.name}: {result.stderr or result.stdout}")


def parse_arrangement(xml_path: str) -> Arrangement:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    arr_name = root.findtext("arrangement", default="")

    tuning = [0] * 6
    el = root.find("tuning")
    if el is not None:
        for i in range(6):
            tuning[i] = _int(el, f"string{i}")
        i = 6
        while el.get(f"string{i}") is not None:
            tuning.append(_int(el, f"string{i}"))
            i += 1

    capo = int(root.findtext("capo", default="0") or 0)

    chord_templates: list[ChordTemplate] = []
    ct_container = root.find("chordTemplates")
    if ct_container is not None:
        for ct in ct_container.findall("chordTemplate"):
            chord_name = ct.get("chordName", "")
            display_name = (ct.get("displayName", "") or "").strip() or chord_name
            width = 6
            while ct.get(f"fret{width}") is not None or ct.get(f"finger{width}") is not None:
                width += 1
            chord_templates.append(
                ChordTemplate(
                    name=chord_name,
                    display_name=display_name,
                    arpeggio=("-arp" in display_name.lower() or _bool(ct, "arp") or _bool(ct, "arpeggio")),
                    fingers=[_int(ct, f"finger{i}", -1) for i in range(width)],
                    frets=[_int(ct, f"fret{i}", -1) for i in range(width)],
                )
            )

    notes: list[Note] = []
    chords: list[Chord] = []
    anchors: list[Anchor] = []
    hand_shapes: list[HandShape] = []

    levels_el = root.find("levels")
    phrases_el = root.find("phrases")
    phrase_iters_el = root.find("phraseIterations")

    all_levels = {}
    if levels_el is not None:
        for level in levels_el.findall("level"):
            all_levels[_int(level, "difficulty")] = level

    def parse_level(level):
        lv_notes = []
        lv_chords = []
        lv_anchors = []
        lv_hs = []
        container = level.find("notes")
        if container is not None:
            for n in container.findall("note"):
                lv_notes.append(_parse_note(n))
        container = level.find("chords")
        if container is not None:
            for ch in container.findall("chord"):
                cid = _int(ch, "chordId")
                chord_notes = []
                cn_container = ch.find("chordNotes")
                if cn_container is not None:
                    for cn in cn_container.findall("chordNote"):
                        chord_notes.append(_parse_note(cn))
                lv_chords.append(Chord(time=_float(ch, "time"), chord_id=cid, notes=chord_notes, high_density=_bool(ch, "highDensity")))
        container = level.find("anchors")
        if container is not None:
            for a in container.findall("anchor"):
                lv_anchors.append(Anchor(time=_float(a, "time"), fret=_int(a, "fret"), width=_int(a, "width", 4)))
        container = level.find("handShapes")
        if container is not None:
            for h in container.findall("handShape"):
                lv_hs.append(HandShape(chord_id=_int(h, "chordId"), start_time=_float(h, "startTime"), end_time=_float(h, "endTime"), arpeggio=_bool(h, "arpeggio") or _bool(h, "arp")))
        lv_notes.sort(key=lambda x: x.time)
        lv_chords.sort(key=lambda x: x.time)
        lv_anchors.sort(key=lambda x: x.time)
        lv_hs.sort(key=lambda x: x.start_time)
        return lv_notes, lv_chords, lv_anchors, lv_hs

    if phrases_el is not None and phrase_iters_el is not None and all_levels:
        phrase_max = {}
        for idx, ph in enumerate(phrases_el.findall("phrase")):
            phrase_max[idx] = _int(ph, "maxDifficulty")
        parsed = {diff: parse_level(level) for diff, level in all_levels.items()}
        note_times = {diff: [n.time for n in parsed[diff][0]] for diff in parsed}
        chord_times = {diff: [c.time for c in parsed[diff][1]] for diff in parsed}
        anchor_times = {diff: [a.time for a in parsed[diff][2]] for diff in parsed}
        hs_times = {diff: [h.start_time for h in parsed[diff][3]] for diff in parsed}
        iters = phrase_iters_el.findall("phraseIteration")
        for idx, it in enumerate(iters):
            start = _float(it, "time")
            end = _float(iters[idx + 1], "time") if idx + 1 < len(iters) else float('inf')
            phrase_id = _int(it, "phraseId")
            diff = phrase_max.get(phrase_id)
            if diff is None or diff not in parsed:
                continue
            lv_notes, lv_chords, lv_anchors, lv_hs = parsed[diff]
            s = bisect.bisect_left(note_times[diff], start)
            e = bisect.bisect_left(note_times[diff], end)
            notes.extend(lv_notes[s:e])
            s = bisect.bisect_left(chord_times[diff], start)
            e = bisect.bisect_left(chord_times[diff], end)
            chords.extend(lv_chords[s:e])
            s = bisect.bisect_left(anchor_times[diff], start)
            e = bisect.bisect_left(anchor_times[diff], end)
            anchors.extend(lv_anchors[s:e])
            s = bisect.bisect_left(hs_times[diff], start)
            e = bisect.bisect_left(hs_times[diff], end)
            hand_shapes.extend(lv_hs[s:e])
    elif all_levels:
        top = max(all_levels)
        notes, chords, anchors, hand_shapes = parse_level(all_levels[top])

    notes.sort(key=lambda n: n.time)
    chords.sort(key=lambda c: c.time)
    anchors.sort(key=lambda a: a.time)
    hand_shapes.sort(key=lambda h: h.start_time)
    return Arrangement(arr_name, tuning, capo, notes, chords, anchors, hand_shapes, chord_templates)


def load_song(extracted_dir: str | Path) -> Song:
    _convert_sng_to_xml(extracted_dir)
    song = Song()
    root_dir = Path(extracted_dir)
    xml_files = sorted(root_dir.rglob("*.xml"))

    manifest_names: dict[str, str] = {}
    for jf in root_dir.rglob("*.json"):
        try:
            data = json.loads(jf.read_text())
            entries = data.get("Entries") or data.get("entries") or {}
            for _k, v in entries.items():
                attrs = v.get("Attributes") or v.get("attributes") or {}
                arr_name = attrs.get("ArrangementName", "")
                if arr_name and arr_name not in ("Vocals", "ShowLights", "JVocals"):
                    manifest_names[jf.stem.lower()] = arr_name
                if not song.title and attrs.get("SongName"):
                    song.title = attrs["SongName"]
                if not song.artist and attrs.get("ArtistName"):
                    song.artist = attrs["ArtistName"]
                if not song.album and attrs.get("AlbumName"):
                    song.album = attrs["AlbumName"]
                if not song.year and attrs.get("SongYear"):
                    try:
                        song.year = int(attrs["SongYear"])
                    except Exception:
                        pass
        except Exception:
            continue

    metadata_loaded = False
    for xml_path in xml_files:
        try:
            root = ET.parse(xml_path).getroot()
        except ET.ParseError:
            continue
        if root.tag != "song":
            continue
        arr_text = (root.findtext("arrangement", default="") or "").lower().strip()
        if arr_text in ("vocals", "showlights", "jvocals"):
            continue
        if not metadata_loaded:
            song.title = song.title or root.findtext("title", default="")
            song.artist = song.artist or root.findtext("artistName", default="")
            song.album = song.album or root.findtext("albumName", default="")
            try:
                song.year = song.year or int(root.findtext("albumYear", default="0") or 0)
            except Exception:
                pass
            try:
                song.song_length = float(root.findtext("songLength", default="0") or 0)
            except Exception:
                pass
            try:
                song.offset = float(root.findtext("offset", default="0") or 0)
            except Exception:
                pass
            ebeats = root.find("ebeats")
            if ebeats is not None:
                for eb in ebeats.findall("ebeat"):
                    song.beats.append(Beat(time=_float(eb, "time"), measure=_int(eb, "measure", -1)))
            sections = root.find("sections")
            if sections is not None:
                for s in sections.findall("section"):
                    song.sections.append(Section(name=s.get("name", ""), number=_int(s, "number"), start_time=_float(s, "startTime")))
            metadata_loaded = True

        arrangement = parse_arrangement(str(xml_path))
        manifest_name = manifest_names.get(xml_path.stem.lower())
        if manifest_name:
            arrangement.name = manifest_name
        else:
            low = arrangement.name.lower().strip()
            name_map = {
                "part real_guitar": "Lead",
                "part real_guitar_22": "Rhythm",
                "part real_bass": "Bass",
                "part real_guitar_bonus": "Bonus Lead",
            }
            if low in name_map:
                arrangement.name = name_map[low]
            elif not arrangement.name or low.startswith("part "):
                stem = xml_path.stem.lower()
                if "lead" in stem:
                    arrangement.name = "Lead"
                elif "rhythm" in stem:
                    arrangement.name = "Rhythm"
                elif "bass" in stem:
                    arrangement.name = "Bass"
                elif "combo" in stem:
                    arrangement.name = "Combo"
                else:
                    arrangement.name = xml_path.stem
        song.arrangements.append(arrangement)

    priority = {"lead": 0, "combo": 1, "rhythm": 2, "bass": 3}
    song.arrangements.sort(key=lambda a: priority.get(a.name.lower(), 99))
    return song


def _decrypt_vocals_sng(data: bytes, platform: str) -> bytes:
    iv = data[8:24]
    encrypted = data[24:-56]
    key = _MAC_KEY if platform == "mac" else _PC_KEY
    ctr = Counter.new(128, initial_value=int.from_bytes(iv, "big"))
    cipher = AES.new(key, AES.MODE_CTR, counter=ctr)
    decrypted = cipher.decrypt(encrypted)
    return zlib.decompress(decrypted[4:])


def parse_lyrics(extracted_dir: str | Path) -> list[dict]:
    for xml_path in sorted(Path(extracted_dir).rglob("*.xml")):
        try:
            root = ET.parse(xml_path).getroot()
        except Exception:
            continue
        if root.tag != "vocals":
            continue
        return [
            {"t": round(float(v.get("time", "0")), 3), "d": round(float(v.get("length", "0")), 3), "w": v.get("lyric", "")}
            for v in root.findall("vocal")
        ]
    platform = _detect_platform(extracted_dir)
    for sng_path in sorted(Path(extracted_dir).rglob("*vocals*.sng")):
        try:
            body = _decrypt_vocals_sng(sng_path.read_bytes(), platform)
        except Exception:
            continue
        entry_size = 60
        header_skip = 16
        if len(body) < header_skip + 4:
            continue
        count = struct.unpack_from("<I", body, header_skip)[0]
        if count == 0 or len(body) < header_skip + 4 + count * entry_size:
            continue
        out = []
        off = header_skip + 4
        for _ in range(count):
            time, _note, length = struct.unpack_from("<fif", body, off)
            lyric_raw = body[off + 12: off + 60]
            nul = lyric_raw.find(b"\x00")
            if nul >= 0:
                lyric_raw = lyric_raw[:nul]
            try:
                lyric = lyric_raw.decode("utf-8")
            except UnicodeDecodeError:
                lyric = lyric_raw.decode("latin-1", errors="replace")
            out.append({"t": round(float(time), 3), "d": round(float(length), 3), "w": lyric})
            off += entry_size
        return out
    return []
