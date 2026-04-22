import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <div className="flex items-center justify-center h-screen bg-surface-sunken">
      <div className="text-center space-y-6">
        <div className="space-y-1">
          <h1 className="font-heading text-2xl font-semibold text-fg-default tracking-tight">
            Lawsumm
          </h1>
          <p className="text-sm text-fg-muted">
            Create your account
          </p>
        </div>
        <SignUp
          appearance={{
            elements: {
              rootBox: "mx-auto",
            },
          }}
        />
      </div>
    </div>
  );
}
