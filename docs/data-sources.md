# 公式データ調査・出典

調査・資料取得: 2026-09-11（日本時間）。名称変更の多い時期のため、実装は2026年新体系を基準にする。

## 採用: 気象庁PULL型XML

- [気象庁の公開案内](https://xml.kishou.go.jp/xmlpull.html)
- [技術資料・XMLスキーマ](https://xml.kishou.go.jp/tec_material.html)
- [気象庁データ高度利用ポータル](https://www.data.jma.go.jp/developer/)
- [高頻度・随時Atom](https://www.data.jma.go.jp/developer/xml/feed/extra.xml)
- [長期・随時Atom](https://www.data.jma.go.jp/developer/xml/feed/extra_l.xml)

認証不要の公式機械可読データ。Atom内のXMLリンクをたどる。HTML画面のスクレイピングはしない。高頻度版は毎分更新し少なくとも直近10分、長期版は毎時更新し数日分を掲載する。公開ページは1日10GB以上のダウンロードをアクセス遮断の対象としている。配信遅延・停止があり、確実な配信には気象業務支援センターなどの利用が案内されている。

本実装は通常1分ごとに短期Atom、初回・空白10分超・1時間ごとに長期Atomも取得する。XMLは既読URLをSQLiteで記録し再ダウンロードを防止。初回は警報系列ごとに最新1件を選び、古い発表履歴を連続通知しない。河川以外は公式官署地域コードで絞ってから取得する。

## 2026年の情報体系

- [新たな防災気象情報](https://www.jma.go.jp/jma/kishou/know/bosai/keiho-update2026/index.html)
- [新電文の技術資料・サンプル](https://www.jma.go.jp/jma/kishou/know/bosai/keiho-update2026/tech-info/index.html)
- [新体系の概要資料](https://www.jma.go.jp/jma/kishou/know/bosai/keiho-update2026/pdf/info2026_outlook2.pdf)

2026年5月29日から新体系。大雨・土砂災害・高潮等の情報名称にレベルを付し、危険警報等を導入。大雨情報は浸水と洪水を対象に扱い、土砂災害の警報は別系列になる。極端な現象は気象防災速報に整理された。

旧名の洪水警報や記録的短時間大雨情報だけを検索する実装は採用しない。VPWW55〜61、VPBS50、VXKO系を読み、経過措置のVXWW50/VPOA50/VPHW系およびVPWW53の洪水も解析する。旧VPWW53の他の注意報は新電文と重複するため現行日付では取り込まない。

## 地域表・河川表

- [気象庁防災ページの公式地域JSON](https://www.jma.go.jp/bosai/common/const/area.json): `bosai/resources/areas.json`。閲覧ページ用の公式JSONであり、契約された公開API仕様とは異なるため、実行の都度依存せず検証済みの表を同梱する。
- [河川予報区域と市区町村の公式ZIP](https://www.jma.go.jp/jma/kishou/know/bosai/keiho-update2026/tech-info/zip/20260527_river-areainfo.zip): 国管理・都道府県管理CSVをUTF-8 JSONへ変換し`bosai/resources/rivers.json`に収録。取得ZIP内のディレクトリは20260714版、CSV表題は20260527時点。338予報区域。

市内の複数警報区域をまとめて選択する。河川表の市全体コードと警報区域コードが異なる場合は、市コードの先頭5桁を照合する。これに加えて電文内のCityCodeも用いる。地域表の更新時は`scripts/update_resources.py`を実行し、差分と`areas`の表示を確認する。

## サンプルの出典

テストfixtureは以下の公式ZIPに含まれるXMLのコピー。内容の原典は気象庁であり、本ソフトウェアのコードライセンスとは分離して扱う。

- [公式サンプル20260326版](https://xml.kishou.go.jp/jmaxml_20260326_Samples.zip)
- [大雨の公式時系列サンプル](https://www.jma.go.jp/jma/kishou/know/bosai/keiho-update2026/tech-info/zip/20260323_sample_timeline_heavyrain.zip)

|fixture|元ファイル|
|---|---|
|rain_0〜7.xml|oame_yokohama/VPWW55_JPTF_170922、170925、170928、170930、170932、170934、170936、170938.xml|
|river.xml|16_08_01_260312_VXKOii.xml|
|river_danger.xml|16_10_01_260312_VXKOii.xml|
|river_emergency.xml|16_12_01_260312_VXKOii.xml|
|record.xml|82_01_02_250630_VPBS50.xml|
|linear.xml|82_01_01_260324_VPBS50.xml|
|landslide.xml|17_04_01_250630_VXWW50.xml|
|legacy.xml|15_08_01_130412_VPWW53.xml|

[気象庁コンテンツ利用規約](https://www.jma.go.jp/jma/kishou/info/coment.html)に従い、原典と加工箇所を示す。地域・河川JSONは抽出加工、fixture XMLはコピーである。

## 採用しなかった候補・今後の拡張

### 気象庁ホームページ内の警報JSON

公式ではあるが閲覧画面用の内部形式は変更され得る。警報の主経路は仕様とサンプルが公開されたXMLに統一した。コード表のみオフラインで同梱する。

### 国土交通省「川の防災情報」

[公式サイト](https://www.river.go.jp/)には水位・雨量・洪水関連情報がある。[利用上の注意](https://www.river.go.jp/kawabou/kwb_apend/html/caution.html)も公開されている。本実装の指定河川洪水予報は気象庁XMLから取得可能なため、画面内部の非公開APIやHTML抽出は使用しない。水位観測値・水位周知河川の独自監視は将来拡張とする。

### Lアラート・自治体の避難情報

[利用申込み](https://www.fmmc.or.jp/commons/download/detail.html)と[FAQ](https://www.fmmc.or.jp/commons/faq/)によると利用概要の確認や手続きが必要で、匿名の汎用APIとは異なる。2026年12月の運営主体変更に伴う申込みスケジュール変更も告知されている。資格情報なしで第三者が構築できる本版には含めない。自治体の避難指示を「気象庁警報から推測」して表示することはしない。

## 通知API

- [Slack Incoming Webhooks](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/): HTTPS JSON POST。チャンネルに紐付いたWebhook。公式冪等キーなし。
- [LINE Notify終了告知](https://developers.line.biz/en/news/2025/04/01/line-notify/): 2025-03-31終了。
- [LINE送信方法](https://developers.line.biz/en/docs/messaging-api/sending-messages/): 公式アカウントのMessaging API Pushを採用。
- [LINE再試行](https://developers.line.biz/en/docs/messaging-api/retrying-api-request/): 同一UUIDの再試行キー、期限24時間、受付済み409。

LINE通知メッセージAPI（電話番号ベース）は別サービスであり、本システムは使用しない。LINEを使う場合に必要なのはMessaging APIチャネルアクセストークンと宛先IDである。

## 警報通知の見通し追加（2026-09-13）

VPWP50を定時フィード `regular.xml` / `regular_l.xml` から取得する。
[公式の時系列情報の解説](https://www.jma.go.jp/jma/kishou/know/bosai/warning_irowake.html)に従い、3時間粒度の予報時間帯をそのまま表示する。今後2時間に重なるPT3Hの時間帯だけを使い、PT24Hなどの長期間の数値を2時間予報と誤表示しない。

fixture `timeline_iida.xml` は [2026-09-11 17時の長野県VPWP50](https://www.data.jma.go.jp/developer/xml/data/20260911075547_0_VPWP50_200000.xml) の飯田市ItemとTimeDefines等を残して他市町村のItemを除いた加工データ。数値・時刻は改変していない。
