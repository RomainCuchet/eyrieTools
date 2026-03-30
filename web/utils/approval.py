import functools


def require_approval(flag_names, message=None):
    """
    Decorator to require user approval before running a function if certain flags are set.
    Args:
        flag_names (list[str]): List of argument names that, if True, require approval.
        message (str, optional): Custom warning message. Defaults to a standard warning.
    """
    default_message = (
        "Warning: This action may be illegal without authorization on the target system. "
        "Proceed only if you have explicit permission."
    )

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import sys

            # Map positional args to their names
            from inspect import signature

            sig = signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            # Check if any flagged argument is True
            triggered = False
            for flag in flag_names:
                if bound_args.arguments.get(flag, False):
                    triggered = True
                    break
            if triggered:
                print(message or default_message)
                resp = input("Do you want to continue? (yes/no): ").strip().lower()
                if resp not in ("yes", "y"):
                    print("Operation cancelled by user.")
                    sys.exit(1)
            return func(*args, **kwargs)

        return wrapper

    return decorator
