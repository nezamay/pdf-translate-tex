import pytest

from translatex.cli import classify_source
from translatex.cli import with_default_command
from translatex.workdir import WORK_DIRNAME
from translatex.workdir import ensure_paper_dir
from translatex.workdir import work_dir


def test_loose_pdf_gets_its_own_directory(tmp_path):
    src = tmp_path / "Some_Paper.pdf"
    src.write_bytes(b"%PDF-1.4\n")

    paper = ensure_paper_dir(src)

    assert paper == tmp_path / "Some_Paper"
    assert (paper / "Some_Paper.pdf").is_file()
    assert not src.exists()


def test_pdf_already_in_place_is_left_alone(tmp_path):
    paper = tmp_path / "Some_Paper"
    paper.mkdir()
    src = paper / "Some_Paper.pdf"
    src.write_bytes(b"%PDF-1.4\n")

    assert ensure_paper_dir(src) == paper
    assert src.is_file()


def test_a_name_collision_stops_instead_of_overwriting(tmp_path):
    paper = tmp_path / "Some_Paper"
    paper.mkdir()
    (paper / "Some_Paper.pdf").write_bytes(b"older copy")
    src = tmp_path / "Some_Paper.pdf"
    src.write_bytes(b"newer copy")

    with pytest.raises(FileExistsError):
        ensure_paper_dir(src)
    assert (paper / "Some_Paper.pdf").read_bytes() == b"older copy"
    assert src.is_file()


def test_work_dir_is_created_under_the_paper(tmp_path):
    assert work_dir(tmp_path) == tmp_path / WORK_DIRNAME
    assert (tmp_path / WORK_DIRNAME).is_dir()


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("2301.01234", "arxiv"),
        ("2301.01234v2", "arxiv"),
        ("math.GT/0309136", "arxiv"),
        ("https://arxiv.org/abs/2301.01234", "arxiv"),
        ("Some_Paper.pdf", "pdf"),
        ("/home/u/books/Some_Paper.pdf", "pdf"),
    ],
)
def test_source_kind_is_guessed_from_the_argument(source, kind):
    assert classify_source(source) == kind


class TestCommandLine:
    def test_a_bare_path_still_means_translate(self):
        assert with_default_command(["paper.pdf"]) == ["translate", "paper.pdf"]

    def test_a_named_command_is_left_alone(self):
        assert with_default_command(["fonts", "paper.pdf"]) == ["fonts", "paper.pdf"]

    def test_a_flag_is_not_mistaken_for_a_path(self):
        assert with_default_command(["--help"]) == ["--help"]

    def test_nothing_at_all_stays_nothing(self):
        assert with_default_command([]) == []
