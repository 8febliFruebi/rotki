<script setup lang="ts">
const btcDerivationGapLimit = ref<string>('20');

const { btcDerivationGapLimit: limit } = storeToRefs(useGeneralSettingsStore());
const { tc } = useI18n();

const successMessage = (limit: string) =>
  tc('general_settings.validation.btc_derivation_gap.success', 0, {
    limit
  });

onMounted(() => {
  set(btcDerivationGapLimit, get(limit).toString());
});
</script>

<template>
  <settings-option
    #default="{ error, success, update }"
    setting="btcDerivationGapLimit"
    :error-message="tc('general_settings.validation.btc_derivation_gap.error')"
    :success-message="successMessage"
  >
    <v-text-field
      v-model.number="btcDerivationGapLimit"
      outlined
      class="general-settings__fields__btc-derivation-gap"
      :label="tc('general_settings.labels.btc_derivation_gap')"
      type="number"
      :success-messages="success"
      :error-messages="error"
      @change="update($event ? parseInt($event) : $event)"
    />
  </settings-option>
</template>
