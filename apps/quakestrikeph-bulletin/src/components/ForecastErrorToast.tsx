import { useEffect } from "react";
import { toast } from "./ui/toast";

export default function ForecastErrorToast({ message }: { message: string }) {
  useEffect(() => {
    toast.add({
      id: "forecast-page-error",
      type: "error",
      title: message,
      description: "Return to the Bulletin, or reload the page to try again.",
      timeout: 0,
    });
  }, [message]);
  return null;
}
