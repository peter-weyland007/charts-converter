from __future__ import annotations

from pathlib import Path

from charts_converter.cli import build_parser
from charts_converter.core import (
    OUTPUT_FORMAT_FEEDPAK,
    _default_work_root,
    _normalize_output_path,
    _render_naming_template,
)
from charts_converter.gui import (
    DEFAULT_INPUT_FORMAT,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_SOURCE_MODE,
    INPUT_FORMATS,
    OUTPUT_FORMATS,
    SOURCE_MODE_BATCH,
    main as gui_main,
    selected_input_format,
    selected_output_extension,
    suggest_output_path,
    suggested_output_name,
)


def test_defaults_are_configured() -> None:
    assert selected_input_format(DEFAULT_INPUT_FORMAT) == INPUT_FORMATS[DEFAULT_INPUT_FORMAT]
    assert selected_output_extension(DEFAULT_OUTPUT_FORMAT) == OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT].extension


def test_single_file_output_uses_expected_name_shape() -> None:
    suggested = Path(suggest_output_path('/tmp/Weezer.psarc', OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT], DEFAULT_SOURCE_MODE))
    assert suggested.name == 'Weezer.feedpak'
    assert suggested_output_name('/tmp/Weezer.psarc', OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT]) == 'Weezer.feedpak'


def test_clone_hero_folder_output_uses_folder_name_shape() -> None:
    suggested = Path(suggest_output_path('/tmp/My Song', OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT], DEFAULT_SOURCE_MODE))
    assert suggested.name == 'My Song.feedpak'
    assert suggested.parent.name == 'My Song'


def test_batch_mode_suggests_output_folder() -> None:
    suggested = Path(suggest_output_path('/tmp/song-inputs', OUTPUT_FORMATS[DEFAULT_OUTPUT_FORMAT], SOURCE_MODE_BATCH))
    assert suggested.name == 'song-inputs-converted'


def test_default_work_root_uses_user_cache_dir() -> None:
    path = _default_work_root(Path('/Volumes/Media/Games/rocksmith-dlc/Some Song.psarc'))
    assert 'charts-converter' in str(path)
    assert str(path).startswith(str(Path.home()))


def test_cli_prog_and_output_choices_are_stable() -> None:
    parser = build_parser()
    assert parser.prog == 'charts-converter'
    subparsers = getattr(parser, '_subparsers', None)
    assert subparsers is not None
    subparsers_action = next(action for action in subparsers._group_actions if hasattr(action, 'choices'))
    convert_parser = subparsers_action.choices['convert']
    output_action = next(action for action in convert_parser._actions if action.dest == 'output_format')
    assert output_action.default == 'feedpak-package'
    assert tuple(sorted(output_action.choices)) == ('feedpak-package', 'loose-chart-folder')


def test_render_template_and_feedpak_extension_are_stable() -> None:
    rendered = _render_naming_template(
        '{artist}_{title}.feedpak',
        title='Hallelujah',
        artist='Paramore',
        album='Brand New Eyes',
        year=2009,
        source_name='Paramore_Hallelujah_v1_DD_p',
        output_format=OUTPUT_FORMAT_FEEDPAK,
    )
    assert rendered == 'Paramore_Hallelujah.feedpak'
    assert _normalize_output_path('/tmp/old-name.zip', OUTPUT_FORMAT_FEEDPAK) == Path('/tmp/old-name.feedpak')


def test_gui_smoke_test_returns_zero_without_real_display(monkeypatch) -> None:
    events: list[str] = []

    class DummyRoot:
        def update_idletasks(self) -> None:
            events.append('update')

        def destroy(self) -> None:
            events.append('destroy')

    monkeypatch.setattr('charts_converter.gui.build_root', lambda: DummyRoot())
    assert gui_main(['--smoke-test']) == 0
    assert events == ['update', 'destroy']
