# 第三者データの出典と利用条件

本リポジトリのMIT Licenseは、気象庁由来のデータに対する権利を付与するものではありません。

- `bosai/resources/areas.json`: [気象庁の地域表](https://www.jma.go.jp/bosai/common/const/area.json)をもとに収録。
- `bosai/resources/rivers.json`: [気象庁の河川予報区域・市区町村対応表](https://www.jma.go.jp/jma/kishou/know/bosai/keiho-update2026/tech-info/zip/20260527_river-areainfo.zip)を抽出し、JSONへ加工。
- `tests/fixtures/*.xml`: 気象庁公式サンプルのコピー。`timeline_iida.xml`のみ他市町村の項目を除去した加工データ。各ファイルのURL・原典は[出典一覧](docs/data-sources.md)を参照。

出典：気象庁ホームページ。加工データおよび通知文は本プロジェクトが作成し、気象庁の公式製品や推奨サービスとして提供するものではありません。

利用・再配布時は[気象庁コンテンツ利用規約](https://www.jma.go.jp/jma/kishou/info/coment.html)と、同ページで案内される公共データ利用規約（第1.0版）に従ってください。出典、加工の表示、および個別の権利表記を維持してください。
