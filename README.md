# 気象庁 防災通知モニター

指定した都道府県・市区町村について気象庁公式XMLを1分ごとに確認し、発表・危険度の変化・解除をLINEまたはSlackへ通知します。Python 3.12以上、外部Pythonパッケージ不要。SQLiteに状態と送信待ちメッセージを保存します。

## 最短セットアップ

Docker EngineとDocker Composeが使える、常時稼働するLinuxサーバーを推奨します。Pythonのローカル実行はLinux / macOSに対応し、WindowsではDocker（Linuxコンテナ）またはWSL2を使ってください。まずこのリポジトリを取得し、そのディレクトリで以下を実行します。

```sh
git clone https://github.com/gameov543-coo/jma-bosai-monitor.git
cd jma-bosai-monitor
cp .env.example .env
chmod 600 .env
```

`.env`をエディタで開き、地域と通知先を設定してください。秘密情報をGitやチャットに貼り付けないでください。

```dotenv
MONITOR_AREAS=長野県 飯田市
MIN_LEVEL=1
CHECK_INTERVAL=60
DRY_RUN=false
# Slack または LINE の少なくとも一方
SLACK_WEBHOOK_URL=
LINE_CHANNEL_ACCESS_TOKEN=ここにMessaging_APIチャネルアクセストークン
LINE_TO=ここに送信先のuserIdまたはgroupId
```

```sh
docker compose build
docker compose run --rm monitor python -m bosai areas
docker compose run --rm monitor python -m bosai test-notification
docker compose up -d
docker compose logs --tail=30 monitor
docker compose exec monitor python -m bosai status
```

`test-notification`は実際の宛先へ「テスト通知・災害情報ではありません」を送信します。受信を確認してから常駐させます。以後、設定した地域に変化があったときだけ通知します。初回は取得できた最新の発表中情報も通知します。

## 監視間隔の選定

既定値と推奨値は **60秒** です。[気象庁の高頻度フィード](https://xml.kishou.go.jp/xmlpull.html)は毎分更新されます。公開フィードへの掲載後、次回取得までの待ち時間は平常時で概ね0〜60秒（従来は0〜300秒）となります。これは配信・取得・通知にかかる時間を除いた目安で、通知の到着保証ではありません。60秒未満の指定は受け付けません。

平常時は随時フィードを1分に1回、長期版は1時間に1回取得し、本文XMLは既読URLを再取得しません。障害復旧時は追加取得があります。予報の5分キャッシュは監視間隔とは独立です。長い処理中は次の取得を重ねず、終了後に次の周期へ進みます。通信量を抑えたい場合は120〜300秒も設定できますが、検知が遅くなるため災害通知には60秒を推奨します。

## 対応する情報と2026年の変更

2026年5月29日開始の新体系に対応しています。旧来の名称だけを検索する実装では、新しい危険警報などを見落とすため、新電文を主として扱います。

|情報|取得・実装方法|
|---|---|
|大雨注意報・警報・危険警報・特別警報|VPWW55の市町村別現在状態。新しい大雨情報は浸水・洪水を対象とする|
|土砂災害注意報・警報・危険警報・特別警報|VPWW56の市町村別現在状態|
|土砂災害警戒情報|VXWW50。新体系ではレベル4土砂災害危険警報の補足情報としても配信される|
|旧体系の洪水警報・注意報|VPWW53の洪水項目を解析。旧電文fixtureの解析も可能。新体系では大雨・河川氾濫情報を主に利用|
|指定河川洪水予報・氾濫警報|VXKO系。公式の河川予報区域と市町村対応表、および電文のCityCodeを使って照合|
|記録的短時間大雨・線状降水帯発生／直前予測|VPBS50の気象防災速報。VPOA50の旧記録的短時間大雨情報にも対応|
|高潮・暴風・波浪・大雪・その他注意報|VPWW57〜61|
|竜巻注意情報|VPHW50/51およびVPBS50の該当情報|

自治体の避難指示、津波、地震、火山、キキクルの格子データはこの版の自動判定対象ではありません。自治体の避難情報は気象庁の警報と別の情報です。拡張候補のLアラート・国交省情報を含め、調査結果は[公式データ調査](docs/data-sources.md)に記載しています。

## 通知の重要度

**通知重要度LEVELはこのシステム独自の3段階**です。自治体・気象庁の5段階の警戒レベルとは別に表示します。

|通知重要度|例|
|---|---|
|LEVEL 1 状況確認|各種注意報、レベル2氾濫注意報|
|LEVEL 2 警戒|警報、旧土砂災害警戒情報、線状降水帯直前予測、竜巻注意情報|
|LEVEL 3 非常に危険|特別警報・危険警報、氾濫危険／発生情報、レベル4以上、記録的短時間大雨、線状降水帯発生|

`MIN_LEVEL=2`なら注意報だけの発表を抑制します。ただし、通知対象の警報から注意報への低下や解除は通知します。解除をLEVEL 1などに置き換えず、明確に「解除」と表示します。注意報なしと危険がないことは同義ではありません。

通知には地域、情報種別、発表時刻（タイムゾーン付き）、通知重要度、原文にある警戒レベル、見出しの要約、公式XMLへのリンク、防災ページへのリンク、前回からの変化を含みます。府県全体の見出しを含むため、文中には指定市以外の状況も記載される場合があります。

## 警報通知に添える約2時間の見通し

警報相当以上（通知重要度LEVEL 2以上）の新規発表・上昇・変更を通知するとき、気象庁の公式時系列情報VPWP50から、その市町村の今後約2時間に重なる予報を添えます。雨量、大雨・土砂災害の危険度を基本とし、風・雪・高潮・波浪の警報では該当する予想も含めます。注意報のみの通知・解除には予報を付けません。予報だけが更新されても再通知しません。

公式データは**3時間単位**です。たとえば19:30時点なら18:00〜21:00と21:00〜24:00の時間帯を表示し、2時間合計雨量などへの補間・換算はしません。予報発表時刻・対象時間帯・出典を明示します。予報は通常5時・11時・17時・23時に更新され、必要に応じた修正もあります。[気象庁の説明](https://www.jma.go.jp/jma/kishou/know/bosai/warning_irowake.html)

予報取得は5秒のタイムアウト、5分間キャッシュで行います。8時間より古い予報や対象市町村・時間帯のない予報は使いません。取得できなくても警報通知は送り、見通しが取得できなかったことを記載します。予報の危険度が低くても現在の警報を解除扱いにはしません。

## 地域設定

複数地域は半角カンマで区切ります。

```dotenv
MONITOR_AREAS=長野県 松本市,長野県 塩尻市,長野県 安曇野市
# 県全体
# MONITOR_AREAS=長野県
# 複数都道府県
# MONITOR_AREAS=長野県,山梨県 甲府市
# 公式7桁警報区域コード
# MONITOR_AREAS=2020201,2020202
```

松本市は「松本市松本」「松本市乗鞍上高地」、塩尻市は「塩尻市塩尻」「塩尻市楢川」をまとめて登録します。北海道・沖縄県の複数予報区にも対応します。同名市の曖昧さを避けるため、市名だけではなく都道府県名も指定してください。公式警報区域より細かな町丁目単位には対応しません。

```sh
python3 -m bosai areas
```

実際に解決された全区域を必ず確認してください。河川通知は「指定市内のどこでも浸水する」という意味ではなく、その市を含む浸水想定区域の河川情報です。記録的短時間大雨などは市より広い発表区域で通知し、その旨を明記します。

地域コード表・河川対応表は気象庁公式資料を同梱しています。取得元と日付は[出典](docs/data-sources.md)を参照してください。

## Slackの設定

1. [Slack App管理画面](https://api.slack.com/apps)でアプリを作成します。
2. **Incoming Webhooks**を有効にします。
3. **Add New Webhook to Workspace**から送信先チャンネルを選択して許可します。
4. 発行された `https://hooks.slack.com/services/...` を`.env`の`SLACK_WEBHOOK_URL`に設定します。
5. `DRY_RUN=false`として`test-notification`を実行します。

送信チャンネルはWebhookを作成した時点で決まります。チャンネル名を別途指定する必要はありません。Webhook URLは秘密情報です。[公式手順](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/)

## LINEの設定

**LINE Notifyは2025年3月31日に終了したため使用しません。** 現行のLINE Messaging APIのPushメッセージを使います。

1. [LINE Official Account Manager](https://manager.line.biz/)でLINE公式アカウントを作成します。
2. 公式アカウントの設定からMessaging APIを有効にし、プロバイダーに紐付けます。
3. [LINE Developers Console](https://developers.line.biz/console/)で対象Messaging APIチャネルを開き、チャネルアクセストークンを発行します。
4. `LINE_CHANNEL_ACCESS_TOKEN`に保存します。チャネルシークレットとは異なります。
5. 自分宛てなら、同じチャネルの基本設定に表示される自分のユーザーIDを`LINE_TO`に設定し、その公式アカウントを友だち追加します。
6. グループ宛てならグループ参加を許可し、公式アカウントを招待します。署名検証済みのWebhookイベントの`source.groupId`を`LINE_TO`に設定します。署名検証には別途チャネルシークレットが必要です。グループID取得用の公開Webhookサーバーは本モニターに含めていません。
7. `test-notification`で端末への受信を確認します。

宛先はLINEの表示名や検索用IDではなく`userId`/`groupId`/`roomId`です。アカウントのプランや送信可能数を確認してください。HTTP 200でもブロックなどで端末に届かない場合があります。Messaging APIの受付成功と端末受信は区別してください。[送信条件](https://developers.line.biz/en/docs/messaging-api/sending-messages/)

送信待ちごとにUUIDの`X-Line-Retry-Key`を保存し、再起動後も同一キーで再試行します。409は`x-line-accepted-request-id`を伴う場合のみ受付済みとして扱います。[公式の再試行仕様](https://developers.line.biz/en/docs/messaging-api/retrying-api-request/)

## ローカル実行

Python 3.12以上を使用します。標準ライブラリだけで動き、`pip install`は不要です。

```sh
python3 -m bosai areas
python3 -m bosai once        # 1回取得・判定・送信
python3 -m bosai run         # 常駐、既定1分間隔
python3 -m bosai status      # 稼働状態・未送信件数
python3 -m bosai healthcheck # 正常なら終了コード0
```

通信・解析に失敗すると`once`は終了コード1、設定不備は2を返します。常駐モードはエラーを記録して次の周期で再試行します。同じDBで監視プロセスを二重起動すると拒否します。

確認だけしたい場合は`DRY_RUN=true`とします。この場合は通知内容を標準出力に表示し、**DB名に`.dry-run`を付けて本番と分離**します。後で本番に切り替えても、確認中に消費した通知状態が本番通知を抑制しません。

環境変数は`.env`より優先します。`.env`は単純な`KEY=value`形式であり、シェルコマンドや変数展開は実行しません。

|変数|既定値・意味|
|---|---|
|MONITOR_AREAS|必須、カンマ区切り|
|CHECK_INTERVAL|60秒（推奨）、許容60〜3600秒|
|MIN_LEVEL|1、許容1〜3|
|HTTP_TIMEOUT|15秒、許容1〜60秒|
|STATE_DB|`data/state.sqlite3`、Composeでは`/data/state.sqlite3`に固定|
|DRY_RUN|false。`.env.example`では安全な初期確認用にtrue|
|SLACK_WEBHOOK_URL|空、Slackを使う場合に設定|
|LINE_CHANNEL_ACCESS_TOKEN / LINE_TO|両方設定するとLINE有効|

## Docker実行・デプロイ

```sh
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 monitor
docker compose exec monitor python -m bosai healthcheck
docker compose restart monitor
docker compose down
```

SQLiteと送信待ちは名前付きボリューム`state`に保存され、コンテナ再起動・再作成でも保持されます。`docker compose down -v`は状態を消すため使わないでください。DBは1インスタンス専用です。レプリカを増やさないでください。

コンテナは非root、ルートファイルシステム読み取り専用、公開ポートなしで動作します。HTTPSの外向き通信とDNSが必要です。標準出力ログは10MB×3ファイルにローテーションします。停止時は処理中のHTTPタイムアウト終了後に停止します。

### 稼働場所の選定

|環境|この用途との相性|
|---|---|
|小規模Linux VPS + Docker Compose|**推奨**。常駐とSQLiteの永続ディスクが簡単。既存VPSなら追加サービス不要|
|自宅サーバー|同じ構成で動く。停電・家庭回線障害・スリープへの対策が必要|
|Cloud Run|常駐設定やスケジューラー、外部永続DBの追加が必要|
|GitHub Actions|定期実行の遅延と永続状態・同時実行制御の工夫が必要。主たる監視先には選ばない|
|AWS Lambda|EventBridgeとDynamoDB等に状態管理を置き換える必要がある|

VPSを新規購入する処理は含みません。Linux VPS上で[公式Docker導入手順](https://docs.docker.com/engine/install/)に従ってEngineとComposeを導入し、本リポジトリ・`.env`を配置して上記の`up -d`を実行します。DockerデーモンをOS起動時に起動する設定にしてください。`restart: unless-stopped`でプロセス異常終了時やホスト再起動後に復帰します。手動停止したものは勝手に再開しません。

MacではDocker DesktopまたはColimaで動作確認できますが、Macのスリープ中は監視できません。常時稼働を必要とする本番はVPSへ移してください。

## アーキテクチャ

```text
scheduler → weather_provider → alert_parser → alert_evaluator
                                      ↓             ↓
                               SQLite state_store + outbox
                                                    ↓
                                      notification_service
                                           ├ Slack Webhook
                                           └ LINE Messaging API
```

- `weather_provider.py`: 気象庁のAtomフィードとXMLを取得。短期・長期を併用、既読URLは再取得しない。
- `alert_parser.py`: 市町村・河川・単発速報を共通モデルへ変換。未知形式で解除を推測しない。
- `alert_evaluator.py`: 種別・重要度・警戒レベルの変化、訂正、閾値、通知文。
- `state_store.py`: SQLiteトランザクション内で前回状態更新と送信待ち追加を一括実行。
- `notification_service.py`: 独立したSlack/LINEアダプター、再送、送信順序の維持。
- `scheduler.py`: 定期確認・停止処理・障害／復旧通知。
- `config.py`, `areas.py`: 設定検証、地域解決、公式地域表。

Discord・メール・Teamsは`Channel.send(text, retry_key)`を実装して登録できます。データソースを増やす場合は`Bulletin`/`Alert`への変換と取得アダプターを追加し、地域と情報種別の識別キーを安定させてください。

## 状態変化と障害対策

- 同じ警報の継続電文や発表時刻だけの更新では再通知しません。名称・重要度・気象庁レベルが変わった場合に通知します。要約だけの訂正も通知します。
- 電文の「取消」は警報の解除と見なしません。保存状態を維持し、取得・解析障害の通知とログで公式情報の確認を促します。
- 解除はその市町村・その情報系列の正常に解析できたスナップショット内で判定します。フィードから消えた、APIが空になった、時刻が古くなったという理由では解除しません。
- 全解除時もスナップショット時刻を保存し、後から取得した古い警報で状態が復活することを防ぎます。
- 単発速報は3時間以内の報告を取り込み、イベントIDと通番で重複を防ぎます。時間経過で「解除」通知は作りません。
- GETはタイムアウト・429・5xxに最大3回、指数バックオフで再試行。XMLサイズは16MiBで制限しDTD/ENTITYを拒否。転送先を制限し、リダイレクトは追いません。
- 通知失敗はDBに保存して30秒から最大1時間の待機で再試行し、`Retry-After`も考慮。401/403など再試行で改善しないエラーは`failed`として保留。
- チャンネル単位で順番を守り、再送待ちの警報を追い越して解除を送信しません。他方のチャンネルには影響しません。
- 23時間を超えた未送信通知は`failed`扱いにして自動再送を止めます。LINEの再試行キーの有効期限は24時間であり、古い災害情報を無制限に再送しません。
- API取得／解析障害は1回だけ運用通知し、復旧時も1回通知します。通知先自体が使えないときはログ・ヘルスチェックで確認します。
- ログにトークン・Webhook URL・HTTP本文を出しません。送信済みキュー、既読履歴、単発イベント状態は30日で整理します。

**Slack Incoming Webhookは冪等キーがないため、受付直後の通信断やDB記録直前の停止では再送が重複する可能性があります。** 通常の同一警報の重複は防ぎますが、この不確定区間で厳密な「必ず1回」を保証することはできません。LINEもAPI受付と端末配送は別です。

## 運用確認・バックアップ

`healthcheck`は取得成功からの経過時間、取得・解析障害、15分以上の滞留、失敗した通知を検知します。Dockerの`unhealthy`だけでは自動再起動しないため、VPS側の監視からヘルス状態を確認してください。ホスト自体の停止を自分自身では通知できません。

設定の変更は`.env`を編集し、`docker compose up -d --force-recreate`で反映します。宛先変更前にはキューの未送信がないことを確認してください。未送信メッセージも現在設定された宛先へ送られます。

バックアップはSQLiteのオンラインバックアップAPIを使います。稼働中のDBファイルだけをコピーするとWALの内容が欠ける場合があります。

```sh
docker compose exec monitor python -c "import sqlite3; s=sqlite3.connect('/data/state.sqlite3'); d=sqlite3.connect('/data/backup.sqlite3'); s.backup(d); d.close(); s.close()"
docker compose cp monitor:/data/backup.sqlite3 ./backup.sqlite3
```

復元時はモニターを停止し、元DBとWAL/SHMを含むディレクトリを退避したうえでバックアップを`state.sqlite3`へ配置し、UID 10001が読み書きできるようにします。

失敗通知があるときは資格情報・上限・ネットワークを修正し、まずテスト通知で復旧を確認します。古い災害通知を手動で再送する前に、現在の公式情報と通知時刻を確認してください。確認済みの失敗を再送せず保留終了するには、監視を停止し `docker compose run --rm monitor python -m bosai dismiss-failures` を実行してから再起動します。

## テスト

実災害も認証情報も不要です。気象庁公式サンプルをfixtureとして使用し、ネットワーク・送信はテストで差し替えます。

```sh
python3 -m unittest discover -s tests -v
# 変更に関係するテストだけ
python3 -m unittest discover -s tests -p test_system.py -k rain_timeline -v
python3 -m unittest discover -s tests -p test_regressions.py -v
```

新規警報、上昇、下降、解除、重複防止、再起動、閾値、古い電文、公式河川対応、単発情報、試験電文除外、形式破損、API障害、Slack、LINE、再試行を検証します。実通知は`test-notification`を別途使います。

実行済みの確認と運用上の制約は[検証記録](docs/verification.md)を参照してください。

## 情報源の制約

公式PULL型フィードは配信保証付きサービスではありません。高頻度版は毎分更新・直近少なくとも10分、長期版は毎時更新・数日間です。本システムは通常1分間隔で短期版を取得し、初回・10分以上の空白・1時間ごとに長期版も取得します。

初回は取得可能な履歴から系列ごとの最新状態を復元します。履歴にない情報は「未確認」であり「警報なし」と断定できません。数日を超える停止では公開履歴外の変化を回収できないため、公式画面で現況を確認してから運用を再開してください。より確実な配信が必要なら、気象業務支援センター等の配信サービスへ取得部分を置き換える設計です。

[気象庁PULL型公開仕様・利用上の留意事項](https://xml.kishou.go.jp/xmlpull.html)と[出典・調査内容](docs/data-sources.md)を確認してください。本システムの通知だけを避難判断の唯一の情報源にしないでください。

## ライセンス・開発への参加

プログラムと独自ドキュメントは[MIT License](LICENSE)で公開します。気象庁由来の地域表・河川表・XMLサンプルには別途[第三者データの表示](THIRD_PARTY_NOTICES.md)が適用されます。本プロジェクトは気象庁の公式サービスではありません。

変更時は上記の自動テストを実行してください。GitHub ActionsでもPython 3.12 / 3.13、Docker内のテスト、Compose設定を確認します。Docker検証で別の設定ファイルを使う場合は `BOSAI_ENV_FILE=/absolute/path/to/example.env docker compose -p bosai-check ...` と指定できます。通常は `.env` を使います。
