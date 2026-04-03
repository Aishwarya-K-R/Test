using Microsoft.AspNetCore.RateLimiting;

namespace Patient_Management_System.Config
{
    public static class RateLimiterConfig
    {
        public static void Configure(RateLimiterOptions options)
        {
            options.AddFixedWindowLimiter("loginLimiter", opt =>
            {
                opt.PermitLimit = 5;
                opt.Window = TimeSpan.FromMinutes(1);
                opt.QueueLimit = 0;
            });

            options.OnRejected = async (context, token) =>
            {
                var logger = context.HttpContext.RequestServices
                    .GetRequiredService<ILoggerFactory>()
                    .CreateLogger("RateLimiter");

                var ip =
                    context.HttpContext.Request.Headers["X-Forwarded-For"].FirstOrDefault()
                    ?? context.HttpContext.Connection.RemoteIpAddress?.MapToIPv4().ToString();

                var endpoint = context.HttpContext.Request.Path;

                logger.LogWarning(
                    "Rate limit exceeded | IP: {IP} | Endpoint: {Endpoint}",
                    ip,
                    endpoint
                );

                context.HttpContext.Response.StatusCode = 429;

                await context.HttpContext.Response.WriteAsJsonAsync(new
                {
                    status = 429,
                    error = "TooManyRequests",
                    message = "Too many login attempts. Please try again later.",
                    timestamp = DateTime.UtcNow
                }, cancellationToken: token);
            };
        }
    }
}