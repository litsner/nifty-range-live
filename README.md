# NIFTY Range Live — Cloud Deployable

## Render deployment
1. Create a GitHub repository and upload these files.
2. In Render: New -> Web Service -> connect the repository.
3. Select Docker runtime. Render will use the Dockerfile.
4. Deploy. Render provides a public `onrender.com` URL.
5. Open that URL on Android and use Add to Home Screen.

Health endpoint: `/api/health`

The Docker image includes Playwright/Chromium. The app opens the NiftyTrader page, captures browser network JSON, extracts strike/LTP/volume/Delta and calculates the requested range.

## Important free-plan limitation
Render free web services can spin down after inactivity. This means the free plan is suitable for opening the dashboard and fetching while you use it, but not for guaranteed always-on 9:15 AM background monitoring. Use an always-on paid service or separate scheduled worker for unattended market-open jobs.

## Local Docker test
`docker build -t nifty-range-live .`
`docker run --rm -p 10000:10000 nifty-range-live`
Open http://127.0.0.1:10000

## Formula
Resistance = highest-volume strike + (same-strike CE LTP × CE Delta) + (next higher strike PE LTP × PE Delta)

Default support = 2nd-highest-volume strike − (same-strike PE LTP × |PE Delta|) − (next lower strike CE LTP × |CE Delta|)
