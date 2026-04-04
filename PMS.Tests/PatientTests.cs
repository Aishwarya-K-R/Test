using System.Net;
using System.Security.Claims;
using FluentAssertions;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Moq;
using Patient_Management_System.Controllers;
using Patient_Management_System.Models;
using Patient_Management_System.Services;
using Xunit;

// Integration test: verifies auth middleware blocks unauthenticated requests
public class PatientTests(CustomWebApplicationFactory factory) : IClassFixture<CustomWebApplicationFactory>
{
    private readonly HttpClient _client = factory.CreateClient();

    [Fact]
    public async Task GetPatients_Should_Return_401_When_No_Token()
    {
        var response = await _client.GetAsync("/api/patients");

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }
}

// Unit test: verifies controller returns 200 when service returns data (no DB/Redis/Kafka needed)
public class PatientControllerTests
{
    [Fact]
    public async Task GetPatients_Should_Return_200_With_Valid_Token()
    {
        var mockService = new Mock<IPatientService>();
        mockService
            .Setup(s => s.GetPatientsAsync(It.IsAny<string>(), It.IsAny<string>(), It.IsAny<string>(), It.IsAny<int>(), It.IsAny<int>()))
            .ReturnsAsync(new List<Patient>
            {
                new() { Id = 1, Name = "Test Patient", Email = "patient@test.com", Address = "123 Test St",
                         DateOfBirth = new DateOnly(1990, 1, 1), RegisteredDate = DateOnly.FromDateTime(DateTime.UtcNow) }
            });

        var controller = new PatientController(mockService.Object);

        // Simulate authenticated user
        controller.ControllerContext = new ControllerContext
        {
            HttpContext = new DefaultHttpContext
            {
                User = new ClaimsPrincipal(new ClaimsIdentity(new[]
                {
                    new Claim(ClaimTypes.NameIdentifier, "1"),
                    new Claim(ClaimTypes.Role, "ADMIN"),
                }, "TestAuth"))
            }
        };

        var result = await controller.GetPatients();

        result.Should().BeOfType<OkObjectResult>();
        (result as OkObjectResult)!.StatusCode.Should().Be(200);
    }
}
