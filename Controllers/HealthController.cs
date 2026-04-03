using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;

[AllowAnonymous]
[ApiController]
[Route("health")]
public class HealthController(IHttpClientFactory clientFactory, IConfiguration config) : ControllerBase
{
    private readonly IHttpClientFactory _clientFactory = clientFactory;
    private readonly IConfiguration _config = config;

    [HttpGet]
    public async Task<IActionResult> GetHealth()
    {
        var serviceName = _config["ServiceName"];

        if (serviceName != "Gateway")
        {
            return Ok(new { status = "Healthy", service = serviceName });
        }

        var client = _clientFactory.CreateClient();

        var results = new Dictionary<string, string>();

        results["auth-service"] = await Check(client, _config["Services:Auth"]);
        results["patient-service"] = await Check(client, _config["Services:Patient"]);
        results["gateway"] = "Healthy";

        return Ok(results);
    }

    private async Task<string> Check(HttpClient client, string url)
    {
        try
        {
            var response = await client.GetAsync(url);
            return response.IsSuccessStatusCode ? "Healthy" : "Unhealthy";
        }
        catch
        {
            return "Unreachable";
        }
    }
}