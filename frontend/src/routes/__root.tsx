/// <reference types="vite/client" />
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'
import {
  HeadContent,
  Outlet,
  Scripts,
  createRootRouteWithContext,
} from '@tanstack/react-router'
import { CacheProvider } from '@emotion/react'
import { Container, CssBaseline, ThemeProvider } from '@mui/material'
import createCache from '@emotion/cache'
import { QueryClientProvider } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import fontsourceVariableRobotoCss from '@fontsource-variable/roboto?url'
import React from 'react'
import { theme } from '~/styles/theme'
import { Header } from '~/components/Header'
import { Footer } from '~/components/Footer'

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    links: [{ rel: 'stylesheet', href: fontsourceVariableRobotoCss }],
  }),
  component: RootComponent,
})

function RootComponent() {
  return (
    <RootDocument>
      <Outlet />
    </RootDocument>
  )
}

function Providers({ children }: { children: React.ReactNode }) {
  const { queryClient } = Route.useRouteContext()
  const [emotionCache] = React.useState(() => createCache({ key: 'css' }))

  return (
    <CacheProvider value={emotionCache}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      </ThemeProvider>
    </CacheProvider>
  )
}

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html>
      <head>
        <HeadContent />
      </head>
      <body>
        <Providers>
          <Header />
          <Container component="main" sx={{ paddingBlock: 4 }}>
            {children}
          </Container>
          <Footer />
        </Providers>

        <TanStackRouterDevtools position="bottom-right" />
        <Scripts />
      </body>
    </html>
  )
}
