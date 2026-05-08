import { createFileRoute } from '@tanstack/react-router'
import { Stack, Typography } from '@mui/material'

export const Route = createFileRoute('/')({
  component: Home,
})

function Home() {
  return (
    <Stack alignItems="center">
      <Typography variant="h1" marginBlockEnd={4}>
      CryoET Catalog
      </Typography>
      <Typography variant="body1">Browse samples cataloged by the scanner.</Typography>
    </Stack>
  )
}
