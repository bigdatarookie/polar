"""Fixed installed harness; launch only through Service and observed launcher."""
from polar.capability_worker import main
raise SystemExit(main())
