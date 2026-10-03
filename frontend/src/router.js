import { createRouter, createWebHistory } from 'vue-router'
import HomeView from './views/HomeView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/catalog', name: 'catalog', component: () => import('./views/CatalogView.vue') },
    { path: '/product/:id', name: 'product', component: () => import('./views/ProductView.vue') },
    { path: '/favourites', name: 'favourites', component: () => import('./views/FavouritesView.vue') },
    { path: '/cart', name: 'cart', component: () => import('./views/CartView.vue') },
    // hideHeader: focused pages without the top navigation bar.
    // fullHeight: app-like pages that fill the screen (no footer, inner scrolling).
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue'), meta: { hideHeader: true } },
    { path: '/register', name: 'register', component: () => import('./views/RegisterView.vue'), meta: { hideHeader: true } },
    { path: '/about', name: 'about', component: () => import('./views/AboutView.vue') },
    { path: '/terms', name: 'terms', component: () => import('./views/LegalView.vue'), meta: { doc: 'terms' } },
    { path: '/returns', name: 'returns', component: () => import('./views/LegalView.vue'), meta: { doc: 'returns' } },
    { path: '/privacy', name: 'privacy', component: () => import('./views/LegalView.vue'), meta: { doc: 'privacy' } },
    { path: '/agent', name: 'agent', component: () => import('./views/AgentView.vue'), meta: { fullHeight: true } },
    { path: '/profile', name: 'profile', component: () => import('./views/ProfileView.vue') },
  ],
  // Section links (#s-3) scroll below the sticky header; every other navigation starts at the top.
  scrollBehavior: (to) => (to.hash ? { el: to.hash, top: 80, behavior: 'smooth' } : { top: 0 }),
})
