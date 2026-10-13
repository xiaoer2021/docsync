
import { computed, ref, readonly } from 'vue';
const openKey = ref('');
const hintLabel = ref('');
const hintSelector = ref('');
let lastKey = '';
let lastCount = 0;
const defaultSelector = '.content .page';
function note(targetKey: string, label = '这里', selector = defaultSelector): boolean {
    if (lastKey === targetKey) {
        lastCount += 1;
    }
    else {
        lastKey = targetKey;
        lastCount = 1;
    }
    if (lastCount < 2)
        return false;
    hintLabel.value = label;
    hintSelector.value = selector;
    openKey.value = targetKey;
    return true;
}
function dismiss() {
    openKey.value = '';
    lastKey = '';
    lastCount = 0;
}
export function useAlreadyHere() {
    return {
        isOpen: computed(() => Boolean(openKey.value)),
        label: readonly(hintLabel),
        selector: readonly(hintSelector),
        note,
        dismiss,
    };
}
