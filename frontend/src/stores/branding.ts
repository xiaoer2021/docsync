
import { computed, ref } from 'vue';
import { defineStore } from 'pinia';
import defaultLogo from '@/assets/logo.png';
import { getBranding, type Branding } from '@/api/branding';
const FALLBACK = '在线表格同步';
export const useBrandingStore = defineStore('branding', () => {
    const name = ref(FALLBACK);
    const title = ref(FALLBACK);
    const tabTitle = ref(FALLBACK);
    const hasLogo = ref(false);
    const logoUpdatedAt = ref<string | null>(null);
    const logoUrl = computed(() => hasLogo.value
        ? `/api/v1/settings/branding/logo?v=${encodeURIComponent(logoUpdatedAt.value || '')}`
        : defaultLogo);
    function apply(next: Branding) {
        name.value = next.name || FALLBACK;
        title.value = next.title || name.value;
        tabTitle.value = next.tab_title || name.value;
        hasLogo.value = next.has_logo;
        logoUpdatedAt.value = next.logo_updated_at;
        syncFavicon();
    }
    function syncFavicon() {
        if (!hasLogo.value)
            return;
        for (const rel of ['icon', 'apple-touch-icon']) {
            const link = document.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
            if (link)
                link.href = logoUrl.value;
        }
    }
    async function load() {
        apply(await getBranding());
    }
    return { name, title, tabTitle, hasLogo, logoUpdatedAt, logoUrl, apply, load };
});
