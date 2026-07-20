"""Tests for Roboflow OBB label import."""

from pathlib import Path

from mooring_fields.import_roboflow_labels import (
    import_roboflow_obb_export,
    roboflow_stem_to_original,
)


class TestRoboflowStemRemap:
    def test_png_rf_hash(self):
        assert (
            roboflow_stem_to_original(
                "AC1_0F1B7DB5_center_z18_png.rf.KNmBtI04qbebF90f06SR.txt"
            )
            == "AC1_0F1B7DB5_center_z18"
        )

    def test_plain_rf_hash(self):
        assert (
            roboflow_stem_to_original("MF_6_032D13F8_south_z18.rf.abc123.txt")
            == "MF_6_032D13F8_south_z18"
        )

    def test_already_clean(self):
        assert (
            roboflow_stem_to_original("MF_6_032D13F8_south_z18.txt")
            == "MF_6_032D13F8_south_z18"
        )


class TestImportRoboflowExport:
    def test_import_rename_backfill_and_empty(self, tmp_path: Path):
        source = tmp_path / "rf"
        (source / "train" / "labels").mkdir(parents=True)
        (source / "valid" / "labels").mkdir(parents=True)

        obb = (
            "0 0.1 0.1 0.2 0.1 0.2 0.2 0.1 0.2\n"
            "0 0.5 0.5 0.6 0.5 0.6 0.6 0.5 0.6\n"
        )
        (source / "train" / "labels" / "siteA_center_z18_png.rf.hash1.txt").write_text(
            obb, encoding="utf-8"
        )
        (source / "train" / "labels" / "siteA_north_z18_png.rf.hash2.txt").write_text(
            "", encoding="utf-8"
        )
        (source / "valid" / "labels" / "siteB_center_z18_png.rf.hash3.txt").write_text(
            obb, encoding="utf-8"
        )

        imagery = tmp_path / "imagery"
        prelabels = tmp_path / "prelabels"
        labels = tmp_path / "labels"
        for split, stems in (
            ("train", ["siteA_center_z18", "siteA_north_z18", "siteA_east_z18"]),
            ("val", ["siteB_center_z18"]),
        ):
            (imagery / split).mkdir(parents=True)
            (prelabels / split).mkdir(parents=True)
            for stem in stems:
                (imagery / split / f"{stem}.png").write_bytes(b"fake")
        # Missing from Roboflow: siteA_east — backfill from prelabel
        (prelabels / "train" / "siteA_east_z18.txt").write_text(obb, encoding="utf-8")

        report = import_roboflow_obb_export(
            source,
            labels_dir=labels,
            imagery_dir=imagery,
            prelabels_dir=prelabels,
        )

        assert report["ok"] is True
        assert (labels / "train" / "siteA_center_z18.txt").read_text(encoding="utf-8").strip()
        assert (labels / "train" / "siteA_north_z18.txt").read_text(encoding="utf-8") == ""
        east = (labels / "train" / "siteA_east_z18.txt").read_text(encoding="utf-8")
        assert east.strip()
        assert len(east.strip().splitlines()[0].split()) == 9
        assert report["splits"]["train"]["roboflow_imported"] == 2
        assert report["splits"]["train"]["roboflow_empty"] == 1
        assert report["splits"]["train"]["backfilled_from_prelabels"] == 1
        assert report["splits"]["train"]["label_files"] == 3
        assert report["splits"]["val"]["label_files"] == 1
        assert (labels / "val" / "siteB_center_z18.txt").exists()
