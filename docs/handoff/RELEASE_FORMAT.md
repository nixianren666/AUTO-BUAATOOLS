# 正式发行与客户端更新识别约定

本约定用于新增版本检查功能，禁止把版本标题当作唯一识别依据。

- `core/version.py` 使用纯数字三段版本，例如`1.2.10`；正式GitHub Release标签严格使用`v1.2.10`。禁止前导零、第四段、构建后缀或预发行后缀冒充正式版。
- 程序版本、网页资源版本、Windows安装器/版本资源、Mac Bundle版本和Release标签必须一致。发布前运行`python scripts/check_release_format.py --tag v1.2.10`，参数必须是**将要实际发布的标签**，不可用假参数替代真实检查。原生构建工作流也执行本地元数据检查。
- 正式Release必须`draft=false`、`prerelease=false`，并按GitHub当前规则设为Latest（`make_latest=true`）；客户端查询公共`/repos/nixianren666/AUTO-BUAATOOLS/releases/latest`。只建Git tag、只改Release标题或上传草稿不会形成可识别的正式更新。发布被撤回的版本不得重新标Latest。
- 版本按数字元组比较，例如1.2.10高于1.2.9；本地候选高于线上版时显示无需降级。预发行测试另用非正式Release，不误通知全部正式用户。
- 客户端只提示版本并打开固定项目的发行页，由用户选择适合Windows/Mac/Linux及架构的附件。不会下载执行远端更新脚本、静默替换EXE或重启。远端正文/链接不作为可执行内容；发行页地址由合法标签与固定项目地址构成。
- 发布仍须完成工程原有的源码/标签/所有平台同期产物核验、原生验证和隐私扫描。版本检查通过不等于平台验收或Release附件完整性通过。
- README继续介绍项目、操作与真实下载入口；更新日志写Release说明，未发行候选不能冒充可下载资产。

GitHub接口依据：[官方Release API文档](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)。公开版本查询不需要用户Token；不要把Token复制进代码、配置模板或交接。
