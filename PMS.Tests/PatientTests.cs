using System.Net;
using FluentAssertions;
using Microsoft.AspNetCore.Mvc.Testing;
using Xunit;
using System.Net.Http.Json;

public class PatientTests(WebApplicationFactory<Program> factory) : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly HttpClient _client = factory.CreateClient();

    [Fact]
    public async Task GetPatients_Should_Return_401_When_No_Token()
    {
        var response = await _client.GetAsync("/api/patients");

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task GetPatients_Should_Return_200_With_Valid_Token()
    {
        var loginResponse = await _client.PostAsJsonAsync("/auth/login", new
        {
            email = "user-1@gmail.com",
            password = "PMS"
        });

        var responseString = await loginResponse.Content.ReadAsStringAsync();
        var token = responseString.Split("Token: ")[1].Trim();

        Console.WriteLine($"Received Token: {token}");

        _client.DefaultRequestHeaders.Authorization =
            new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", token);

        var response = await _client.GetAsync("/api/patients");

        response.StatusCode.Should().Be(HttpStatusCode.OK);
    }
}