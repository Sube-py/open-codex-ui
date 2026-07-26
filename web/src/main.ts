import { createApp } from 'vue'
import PrimeVue from 'primevue/config'
import { definePreset } from '@primeuix/themes'
import Aura from '@primeuix/themes/aura'

import App from './App.vue'
import { initializeColorScheme } from './composables/useColorScheme'
import router from './router'
import 'primeicons/primeicons.css'
import './styles/index.css'

const OpenCodexUiPreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: '{teal.50}',
      100: '{teal.100}',
      200: '{teal.200}',
      300: '{teal.300}',
      400: '{teal.400}',
      500: '{teal.500}',
      600: '{teal.600}',
      700: '{teal.700}',
      800: '{teal.800}',
      900: '{teal.900}',
      950: '{teal.950}',
    },
    colorScheme: {
      light: {
        surface: {
          0: '#ffffff',
          50: '#f7f8f7',
          100: '#eff1ef',
          200: '#dfe3e0',
          300: '#c8ceca',
          400: '#9ea7a1',
          500: '#77817b',
          600: '#5b645f',
          700: '#444b47',
          800: '#2d322f',
          900: '#202421',
          950: '#121513',
        },
      },
      dark: {
        surface: {
          0: '#ffffff',
          50: '#f4f6f4',
          100: '#e4e8e5',
          200: '#c8ceca',
          300: '#a9b1ac',
          400: '#858f89',
          500: '#67716b',
          600: '#505953',
          700: '#3a403c',
          800: '#292e2b',
          900: '#202421',
          950: '#141715',
        },
      },
    },
  },
})

initializeColorScheme()

const app = createApp(App)

app.use(PrimeVue, {
  ripple: true,
  theme: {
    preset: OpenCodexUiPreset,
    options: {
      darkModeSelector: '.app-dark',
      cssLayer: false,
    },
  },
})
app.use(router)

app.mount('#app')
