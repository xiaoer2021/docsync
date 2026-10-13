
export const PRODUCT_NAME = '在线表格同步';
export interface Platform {
    key: string;
    label: string;
    sheetNoun: string;
    color: string;
    enabled: boolean;
    note?: string;
    keyLabel: string;
    secretLabel: string;
    keyPlaceholder: string;
    credentialHint: string;
    needsOperator: boolean;
    needsCredentials?: boolean;
}
export const PLATFORMS: Platform[] = [
    {
        key: 'dingtalk',
        label: '钉钉',
        sheetNoun: '子表',
        color: '#1c7df0',
        enabled: true,
        keyLabel: 'AppKey',
        secretLabel: 'AppSecret',
        keyPlaceholder: '形如 dingxxxxxxxxxxxx',
        credentialHint: '钉钉开放平台 → 应用开发 → 企业内部应用 → 创建应用，创建完就能看到这两个值。',
        needsOperator: true,
    },
    {
        key: 'feishu',
        label: '飞书',
        sheetNoun: '数据表',
        color: '#3370ff',
        enabled: true,
        keyLabel: 'App ID',
        secretLabel: 'App Secret',
        keyPlaceholder: '形如 cli_xxxxxxxxxxxx',
        credentialHint: '飞书开放平台 → 开发者后台 → 创建企业自建应用，建好在「凭证与基础信息」里看这两个值。',
        needsOperator: false,
    },
    {
        key: 'wps_api',
        label: 'WPS 开发者',
        sheetNoun: '工作表',
        color: '#e6432d',
        enabled: true,
        keyLabel: 'AppKey',
        secretLabel: 'AppSecret',
        keyPlaceholder: '开放平台控制台里那串',
        credentialHint: '金山文档开放平台（developer.kdocs.cn）→ 创建应用 → 在应用详情里看 AppKey / AppSecret。' +
            '注意：开放平台要**企业认证**，个人账号建不了应用。',
        needsOperator: false,
    },
    {
        key: 'wps',
        label: 'WPS 个人',
        sheetNoun: '工作表',
        color: '#fe3e53',
        enabled: true,
        keyLabel: '',
        secretLabel: '',
        keyPlaceholder: '',
        credentialHint: '',
        needsOperator: false,
        needsCredentials: false,
    },
    {
        key: 'google',
        label: 'Google Docs',
        sheetNoun: '工作表',
        color: '#1a73e8',
        enabled: false,
        note: '待接入',
        keyLabel: 'Client ID',
        secretLabel: 'Client Secret',
        keyPlaceholder: '',
        credentialHint: '',
        needsOperator: false,
    },
];
export function platformOf(key: string | null | undefined): Platform {
    return PLATFORMS.find((p) => p.key === key) || PLATFORMS[0];
}
export function isPending(key: string | null | undefined): boolean {
    const platform = platformOf(key);
    return platform.enabled && platform.note === '接入中';
}
