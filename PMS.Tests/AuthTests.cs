using System.Net;
using FluentAssertions;
using Microsoft.AspNetCore.Mvc.Testing;
using Xunit;
using System.Net.Http.Json;
public class AuthTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly HttpClient _client = factory.CreateClient();

    [Fact]
    public async Task Login_Returns_Token_When_Credentials_Are_Valid()
    {
        var response = await _client.PostAsJsonAsync("/auth/login", new
        {
            email = "user-1@gmail.com",
            password = "PMS"
        });

        response.StatusCode.Should().Be(HttpStatusCode.OK);
    }

    [Fact]
    public async Task Login_Should_Return_Unauthorized_For_Invalid_Password()
    {
        var response = await _client.PostAsJsonAsync("/auth/login", new
        {
            email = "user-1@gmail.com",
            password = "user"
        });

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }
}