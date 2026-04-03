using System.Net;
using FluentAssertions;
using Microsoft.AspNetCore.Mvc.Testing;
using Xunit;
using System.Net.Http.Json;

public class RateLimitingTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly HttpClient _client = factory.CreateClient();

    [Fact]
    public async Task Login_Should_Return_429_When_Rate_Limit_Exceeded()
    {
        for (int i = 0; i < 6; i++)
        {
            await _client.PostAsJsonAsync("/auth/login", new
            {
                email = "user-1@gmail.com",
                password = "user"
            });
        }

        var response = await _client.PostAsJsonAsync("/auth/login", new
        {
            email = "user-1@gmail.com",
            password = "user"
        });

        response.StatusCode.Should().Be((HttpStatusCode)429);
    }
}