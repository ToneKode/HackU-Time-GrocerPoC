import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router.js'
import { i18n } from './i18n/index.js'
import { loadDatabaseCatalog } from './data/loadShelf.js'
import './lib/theme.js'
import './style.css'
import './shop.css'

loadDatabaseCatalog()
createApp(App).use(router).use(i18n).mount('#app')
