import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Opens a page's form when the link asks for it (`?new=1`, as Quick actions
 * sends), then takes the flag off the URL so a reload or the back button
 * doesn't open it again. Works when already on the page, too.
 */
export function useOpenFromLink(open: () => void, flag = "new") {
  const [params, setParams] = useSearchParams();
  const asked = params.get(flag) === "1";
  useEffect(() => {
    if (!asked) return;
    open();
    setParams((p) => { p.delete(flag); return p; }, { replace: true });
    // `open` is a state setter wrapper; re-running for a new identity isn't wanted.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asked, flag, setParams]);
}
